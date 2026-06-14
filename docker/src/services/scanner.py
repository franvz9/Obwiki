from __future__ import annotations
from ..paths import INBOX_DIR, META_DIR, WIKI_DIR, COMMUNITIES_DIR, LLMWIKI_DIR, OPS_DIR, INDEX_FILE, OVERVIEW_FILE, LOG_FILE, SCHEMA_FILE, CACHE_DIR

import hashlib
from pathlib import Path
from typing import Optional

import aiosqlite


class Scanner:
    def __init__(self, db: aiosqlite.Connection, source_registry=None):
        self.db = db
        self.sr = source_registry

    async def scan_kb(self, kb_id: str, root_path: str) -> dict:
        root = Path(root_path)
        raw_dir = root / INBOX_DIR
        if not raw_dir.exists():
            return {"added": 0, "updated": 0, "total": 0}

        from .parsers import parse_document

        added, updated, indexed = 0, 0, 0
        patterns = ("*.md", "*.pdf", "*.docx", "*.pptx", "*.xlsx", "*.xls",
                     "*.txt", "*.html", "*.csv", "*.json", "*.xml", "*.rst")
        seen = set()
        for pattern in patterns:
            for f in raw_dir.rglob(pattern):
                if any(p.startswith(".") for p in f.parts):
                    continue
                if f.name in seen:
                    continue
                seen.add(f.name)
                try:
                    content = parse_document(str(f))
                except Exception:
                    continue

                file_hash = hashlib.sha256(content.encode()).hexdigest()
                rel_path = str(f.relative_to(root))

                # Register with SourceRegistry (if available)
                if self.sr:
                    old_status = await self.sr.register(kb_id, rel_path, content)
                    if old_status == "raw" or old_status not in ("indexed", "extracted", "extracting"):
                        added += 1
                    else:
                        updated += 1

                    # Update FTS5 index
                    existing_hash = await self._get_hash(kb_id, rel_path)
                    if existing_hash is None:
                        await self._insert_file(kb_id, rel_path, f.stem, content, file_hash)
                    elif existing_hash != file_hash:
                        await self._update_file(kb_id, rel_path, content, file_hash)

                    # Mark as indexed
                    if old_status in ("raw", None):
                        await self.sr.set_status(kb_id, rel_path, "indexed")
                        indexed += 1
                else:
                    existing_hash = await self._get_hash(kb_id, rel_path)
                    if existing_hash is None:
                        await self._insert_file(kb_id, rel_path, f.stem, content, file_hash)
                        added += 1
                    elif existing_hash != file_hash:
                        await self._update_file(kb_id, rel_path, content, file_hash)
                        updated += 1

        # Also index wiki pages (not just inbox)
        from .wiki_schema import find_wiki_dir
        wiki_dir = find_wiki_dir(root)
        if wiki_dir.exists():
            for md_file in wiki_dir.rglob("*.md"):
                if md_file.name in ("index.md", "overview.md", "log.md"):
                    continue
                try:
                    content = md_file.read_text(encoding="utf-8")
                except Exception:
                    continue
                rel_path = str(md_file.relative_to(root))
                file_hash = hashlib.sha256(content.encode()).hexdigest()
                existing_hash = await self._get_hash(kb_id, rel_path)
                if existing_hash is None:
                    await self._insert_file(kb_id, rel_path, md_file.stem, content, file_hash)
                elif existing_hash != file_hash:
                    await self._update_file(kb_id, rel_path, content, file_hash)

        total = await self._count_files(kb_id)
        return {"added": added, "updated": updated, "indexed": indexed, "total": total}

    async def _get_hash(self, kb_id: str, path: str) -> Optional[str]:
        async with self.db.execute(
            "SELECT content_hash FROM file_hashes WHERE kb_id = ? AND path = ?", (kb_id, path)
        ) as cursor:
            row = await cursor.fetchone()
            return row["content_hash"] if row else None

    async def _insert_file(self, kb_id: str, path: str, title: str, content: str, file_hash: str) -> None:
        await self.db.execute(
            "INSERT INTO files_fts (kb_id, path, title, content) VALUES (?, ?, ?, ?)",
            (kb_id, path, title, content),
        )
        await self.db.execute(
            "INSERT INTO file_hashes (kb_id, path, content_hash) VALUES (?, ?, ?)",
            (kb_id, path, file_hash),
        )
        await self.db.commit()

    async def _update_file(self, kb_id: str, path: str, content: str, file_hash: str) -> None:
        await self.db.execute(
            "UPDATE files_fts SET content = ? WHERE kb_id = ? AND path = ?",
            (content, kb_id, path),
        )
        await self.db.execute(
            "UPDATE file_hashes SET content_hash = ? WHERE kb_id = ? AND path = ?",
            (file_hash, kb_id, path),
        )
        await self.db.commit()

    async def _count_files(self, kb_id: str) -> int:
        async with self.db.execute(
            "SELECT COUNT(*) as cnt FROM files_fts WHERE kb_id = ?", (kb_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row["cnt"] if row else 0

    async def search(self, kb_id: str, query: str, limit: int = 20, offset: int = 0) -> list[dict]:
        results = []
        async with self.db.execute(
            "SELECT kb_id, path, title, snippet(files_fts, 2, '<b>', '</b>', '...', 40) as snippet "
            "FROM files_fts WHERE kb_id = ? AND files_fts MATCH ? LIMIT ? OFFSET ?",
            (kb_id, query, limit, offset),
        ) as cursor:
            async for row in cursor:
                results.append(dict(row))
        return results

    async def get_tree(self, kb_id: str, root_path: str) -> dict:
        root = Path(root_path)
        if not root.exists():
            return {"name": root.name, "children": []}
        return _build_tree(root, root)


def _build_tree(current: Path, root: Path) -> dict:
    children = []
    try:
        entries = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name))
    except PermissionError:
        return {"name": current.name, "children": []}

    for entry in entries:
        if entry.name.startswith(".") and entry.name != ".llmwiki":
            continue
        if entry.is_dir():
            children.append(_build_tree(entry, root))
        elif entry.suffix == ".md":
            children.append({
                "name": entry.name,
                "path": str(entry.relative_to(root)),
                "type": "file",
            })
    return {
        "name": current.name,
        "path": str(current.relative_to(root)) if current != root else "",
        "type": "directory",
        "children": children,
    }
