"""Inbox organizer — classify and move existing files to subdirectories without re-extraction."""

from __future__ import annotations

import shutil
from pathlib import Path

import aiosqlite

from ..paths import INBOX_DIR

CATEGORIES = {
    "papers": ["paper", "papers"],
    "documents": ["document", "documents"],
    "notes": ["note", "notes"],
    "conversations": ["conversation", "conversations"],
    "memories": ["memory", "memories"],
    "data": ["data"],
}


class Organizer:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def organize(self, kb_id: str, root_path: str) -> dict:
        root = Path(root_path)
        inbox = root / INBOX_DIR

        if not inbox.exists():
            return {"status": "no inbox"}

        # Create category dirs
        for cat in CATEGORIES:
            (inbox / cat).mkdir(parents=True, exist_ok=True)

        moved = 0
        errors = 0

        # Find files directly in inbox root (not in subdirs)
        for src_file in inbox.iterdir():
            if not src_file.is_file() or src_file.name.startswith("."):
                continue

            rel = str(src_file.relative_to(root))
            doc_class = self._classify(src_file)

            cat_dir = CATEGORIES.get(doc_class, CATEGORIES["documents"])
            target = inbox / doc_class / src_file.name
            if target.exists():
                stem = src_file.stem
                target = inbox / doc_class / f"{stem}_{int(src_file.stat().st_mtime)}{src_file.suffix}"

            try:
                # Set status to organizing before move
                await self.db.execute(
                    "UPDATE sources SET status='organizing' WHERE kb_id=? AND path=?",
                    (kb_id, rel),
                )
                shutil.move(str(src_file), str(target))
                new_rel = str(target.relative_to(root))

                # Update source registry
                await self.db.execute(
                    "UPDATE sources SET path=?, status='indexed' WHERE kb_id=? AND path=?",
                    (new_rel, kb_id, rel),
                )
                await self.db.execute(
                    "UPDATE file_hashes SET path = ? WHERE kb_id = ? AND path = ?",
                    (new_rel, kb_id, rel),
                )
                await self.db.commit()
                moved += 1
            except Exception:
                errors += 1

        return {"moved": moved, "errors": errors}

    @staticmethod
    def _classify(file_path: Path) -> str:
        ext = file_path.suffix.lower()
        name = file_path.stem.lower()

        # By extension
        if ext in (".xlsx", ".xls", ".csv", ".ods"):
            return "data"
        if ext in (".pdf",):
            return "papers"

        # By name patterns
        if any(k in name for k in ("chat", "conversation", "对话", "聊天", "log")):
            return "conversations"
        if any(k in name for k in ("note", "笔记", "todo", "standup", "meeting", "会议")):
            return "notes"
        if any(k in name for k in ("memory", "记忆", "agent", "entity")):
            return "memories"
        if any(k in name for k in ("paper", "文献", "paper", "review", "article")):
            return "papers"
        if any(k in name for k in ("report", "报告", "proposal", "方案", "项目", "plan")):
            return "documents"

        # Try to peek at content
        try:
            content = file_path.read_text(encoding="utf-8")[:1000].lower()
            if any(k in content for k in ("abstract", "doi", "journal", "citation", "references")):
                return "papers"
            if any(k in content for k in ("user:", "assistant:", "dialogue", "chat")):
                return "conversations"
            if any(k in content for k in ("memory", "entity:", "relation:")):
                return "memories"
            if any(k in content for k in ("会议", "standup", "todo")):
                return "notes"
        except Exception:
            pass

        return "documents"
