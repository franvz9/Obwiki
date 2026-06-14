"""Cascade deletion — when source files are deleted, clean up related wiki pages.

Inspired by nashsu/llm_wiki src/lib/source-lifecycle.ts (deleteSourceFiles)
and src/lib/wiki-page-delete.ts (cascadeDeleteWikiPagesWithRefs).

Logic:
1. Delete source files + .cache
2. Scan all wiki pages for `sources:` frontmatter referencing deleted files
3. If a page has no surviving sources → cascade-delete the page
4. If a page has surviving sources → rewrite frontmatter (keep survivors only)
5. Clean wikilinks, index.md, and log the deletion
"""

from __future__ import annotations
from ..paths import INBOX_DIR, META_DIR, WIKI_DIR, COMMUNITIES_DIR, LLMWIKI_DIR, OPS_DIR, INDEX_FILE, OVERVIEW_FILE, LOG_FILE, SCHEMA_FILE, CACHE_DIR

import json
import re
import shutil
from datetime import date
from pathlib import Path

import aiosqlite
import yaml

from .source_registry import SourceRegistry


class SourceCleanup:
    def __init__(self, db: aiosqlite.Connection, source_registry: SourceRegistry):
        self.db = db
        self.sr = source_registry

    async def delete_source_files(
        self, kb_id: str, root_path: str, source_paths: list[str],
    ) -> dict:
        """Delete source files and cascade-clean wiki pages. Returns deletion report."""
        root = Path(root_path)
        raw_dir = root / INBOX_DIR

        # Find wiki directory
        from .wiki_schema import find_wiki_dir
        wiki_dir = find_wiki_dir(root)
        if not wiki_dir.exists():
            return {"deleted_source_files": [], "deleted_wiki_pages": [], "rewritten_wiki_pages": 0}

        deleted_files = []
        deleted_wiki_pages = []
        rewritten_pages = 0

        # Build set of deleting identities for matching
        deleting_keys = set()
        for sp in source_paths:
            src_file = root / sp
            # Normalize
            normalized = str(src_file.relative_to(root)) if src_file.is_relative_to(root) else sp
            deleting_keys.add(normalized)
            deleting_keys.add(src_file.name)
            deleting_keys.add(src_file.stem)

        # Step 1: Collect all wiki pages that reference deleted sources
        affected_wiki: dict[str, list[str]] = {}  # wiki_path -> surviving sources

        if wiki_dir.exists():
            for md_file in wiki_dir.rglob("*.md"):
                if md_file.name in ("index.md", "overview.md"):
                    continue
                try:
                    text = md_file.read_text(encoding="utf-8")
                except Exception:
                    continue

                fm = _parse_frontmatter(text)
                sources = fm.get("sources", [])
                if isinstance(sources, str):
                    sources = [sources]
                if not isinstance(sources, list) or len(sources) == 0:
                    continue

                # Filter out deleted sources
                survivors = [
                    s for s in sources
                    if not _source_matches_deleted(s, deleting_keys)
                ]

                if len(survivors) < len(sources):
                    wiki_rel = str(md_file.relative_to(root))
                    affected_wiki[wiki_rel] = survivors

        # Step 2: Delete or rewrite affected wiki pages
        for wiki_path, survivors in affected_wiki.items():
            wf = root / wiki_path

            if len(survivors) == 0:
                # Cascade delete the wiki page
                await self._delete_wiki_page(kb_id, wf, root)
                deleted_wiki_pages.append(wiki_path)
            else:
                # Rewrite frontmatter with survivors only
                try:
                    text = wf.read_text(encoding="utf-8")
                    new_text = _replace_sources_in_frontmatter(text, survivors)
                    wf.write_text(new_text, encoding="utf-8")
                    rewritten_pages += 1
                except Exception:
                    pass

        # Step 3: Delete source files + cache from disk
        for sp in source_paths:
            sf = root / sp
            if sf.exists():
                sf.unlink()
                deleted_files.append(sp)
            # Clean cache
            cache_dir = sf.parent / ".cache"
            cache_file = cache_dir / f"{sf.name}.txt"
            if cache_file.exists():
                cache_file.unlink()
            # Remove from SourceRegistry
            await self.sr.delete(kb_id, sp)
            # Remove from FTS + file_hashes
            await self._remove_from_index(kb_id, sp)

        # Step 4: Clean wikilinks in remaining pages
        await self._clean_dangling_wikilinks(root, deleted_wiki_pages)

        # Step 5: Rebuild index
        from .extractor import Extractor  # avoid circular import at module level
        # Just rebuild index inline
        await self._rebuild_index(wiki_dir)

        # Step 6: Log deletion
        await self._append_delete_log(root, deleted_files, deleted_wiki_pages, rewritten_pages)

        return {
            "deleted_source_files": deleted_files,
            "deleted_wiki_pages": deleted_wiki_pages,
            "rewritten_wiki_pages": rewritten_pages,
        }

    async def _delete_wiki_page(self, kb_id: str, file_path: Path, root: Path) -> None:
        """Delete a wiki page and its FTS5 entry."""
        rel = str(file_path.relative_to(root))
        file_path.unlink(missing_ok=True)
        await self._remove_from_index(kb_id, rel)

    async def _remove_from_index(self, kb_id: str, path: str) -> None:
        try:
            await self.db.execute(
                "DELETE FROM files_fts WHERE kb_id=? AND path=?", (kb_id, path)
            )
            await self.db.execute(
                "DELETE FROM file_hashes WHERE kb_id=? AND path=?", (kb_id, path)
            )
            await self.db.commit()
        except Exception:
            pass  # FTS5 may not have an entry

    async def _clean_dangling_wikilinks(self, root: Path, deleted_paths: list[str]) -> None:
        """Remove [[wikilinks]] pointing to deleted pages from remaining pages."""
        deleted_slugs = set()
        for dp in deleted_paths:
            stem = Path(dp).stem
            deleted_slugs.add(stem)
            deleted_slugs.add(stem.lower().replace(" ", "-"))

        from .wiki_schema import find_wiki_dir
        wiki_dir = find_wiki_dir(root)
        if not wiki_dir.exists():
            return

        for md_file in wiki_dir.rglob("*.md"):
            if md_file.name == "_never_match":
                continue
            try:
                text = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            modified = False
            for slug in deleted_slugs:
                pattern = rf"\[\[{re.escape(slug)}\]\]"
                if re.search(pattern, text, re.IGNORECASE):
                    text = re.sub(pattern, "", text, flags=re.IGNORECASE)
                    modified = True

            if modified:
                md_file.write_text(text, encoding="utf-8")

    async def _rebuild_index(self, wiki_dir: Path) -> None:
        entries = []
        for md_file in sorted(wiki_dir.rglob("*.md")):
            if md_file.name in ("index.md", "overview.md"):
                continue
            rel = md_file.relative_to(wiki_dir)
            try:
                text = md_file.read_text(encoding="utf-8")
                first_line = ""
                in_fm = False
                for line in text.split("\n"):
                    ls = line.strip()
                    if ls == "---":
                        in_fm = not in_fm
                        continue
                    if not in_fm and ls and not ls.startswith("#"):
                        first_line = ls.lstrip("# ").strip()
                        break
                import re as _re
                first_line = _re.sub(r'\[\[.*?\]\]', '', first_line)
                first_line = _re.sub(r'\[\[[^\]]*$', '', first_line)
                first_line = first_line.strip()[:80]
                entries.append(f"- {rel.with_suffix('')}.md — {first_line}")
            except Exception:
                entries.append(f"- {rel.with_suffix('')}.md")

        today = date.today().isoformat()
        index = f"# Wiki Index\n\n*Last updated: {today}*\n\n"
        index += "\n".join(entries) + "\n"
        (root / META_DIR / INDEX_FILE).write_text(index, encoding="utf-8")

    async def _append_delete_log(self, root: Path, deleted_sources: list[str],
                                  deleted_wiki: list[str], rewritten: int) -> None:
        log_dir = root / OPS_DIR
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "log.md"
        existing = log_path.read_text(encoding="utf-8") if log_path.exists() else "# Operation Log\n\n"
        today = date.today().isoformat()
        entry = (
            f"## [{today}] delete | {len(deleted_sources)} source(s)\n\n"
            f"- Deleted sources: {', '.join(deleted_sources[:5])}\n"
            f"- Deleted wiki pages: {len(deleted_wiki)}\n"
            f"- Rewritten wiki pages: {rewritten}\n\n"
        )
        log_path.write_text(existing + entry, encoding="utf-8")


def _parse_frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    try:
        end = text.index("---", 3)
        return yaml.safe_load(text[3:end]) or {}
    except Exception:
        return {}


def _replace_sources_in_frontmatter(text: str, survivors: list[str]) -> str:
    """Rewrite the sources: line in YAML frontmatter."""
    if not text.startswith("---"):
        return text
    try:
        end = text.index("---", 3)
        fm = text[3:end]
        body = text[end + 3:]

        # Replace sources: block
        fm_new = re.sub(
            r'^sources:\s*\[.*?\]',
            f'sources: [{", ".join(survivors)}]',
            fm,
            flags=re.MULTILINE | re.DOTALL,
        )
        if "sources:" not in fm_new:
            fm_new = re.sub(
                r'^sources:\s*\n(\s+-.*\n)*',
                f'sources:\n' + '\n'.join(f'  - {s}' for s in survivors) + '\n',
                fm,
                flags=re.MULTILINE,
            )

        return f"---{fm_new}---{body}"
    except Exception:
        return text


def _source_matches_deleted(source_ref: str, deleting_keys: set[str]) -> bool:
    """Check if a source reference matches any deleted file."""
    ref_lower = source_ref.lower().strip()
    for key in deleting_keys:
        key_lower = key.lower().strip()
        if ref_lower == key_lower:
            return True
        if key_lower in ref_lower or ref_lower in key_lower:
            return True
    return False
