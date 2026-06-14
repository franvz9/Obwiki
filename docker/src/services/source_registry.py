"""Source Registry — tracks every imported source file's processing lifecycle.

State machine:  raw → indexed → extracting → extracted
                     ↓                       ↓
                   error ←─────────────── error

Inspired by nashsu/llm_wiki src/lib/source-lifecycle.ts
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

STATUSES = ("raw", "indexed", "organizing", "extracting", "dedup_check", "extracted", "error", "cancelled")
INGESTABLE_EXTS = {
    "md", "mdx", "txt", "pdf", "doc", "docx", "pptx",
    "xlsx", "xls", "odt", "odp", "ods", "csv", "json",
    "html", "htm", "rtf", "xml", "yaml", "yml",
}

def _now() -> str:
    return datetime.now().isoformat()


class SourceRegistry:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    # ── CRUD ──────────────────────────────────────────────────

    async def register(self, kb_id: str, file_path: str, content: str) -> str:
        """Register or update a source file. Returns the new status based on change detection."""
        p = Path(file_path)
        file_name = p.name
        file_type = p.suffix.lstrip(".").lower()
        file_size = p.stat().st_size if p.exists() else 0
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        modified_at = datetime.fromtimestamp(p.stat().st_mtime, ).isoformat() if p.exists() else _now()

        existing = await self.get(kb_id, file_path)
        if existing:
            if existing["content_hash"] == content_hash:
                return existing["status"]  # unchanged

            await self.db.execute(
                """UPDATE sources SET file_size=?, content_hash=?, modified_at=?, error_log=''
                   WHERE kb_id=? AND path=?""",
                (file_size, content_hash, modified_at, kb_id, file_path),
            )
            # Reset to raw if content changed
            await self.set_status(kb_id, file_path, "raw")
            await self.db.commit()
            return "raw"
        else:
            sid = uuid.uuid4().hex[:12]
            now = _now()
            await self.db.execute(
                """INSERT INTO sources (id, kb_id, path, file_name, file_type, file_size,
                   content_hash, status, created_at, modified_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'raw', ?, ?)""",
                (sid, kb_id, file_path, file_name, file_type, file_size, content_hash, now, modified_at),
            )
            await self.db.commit()
            return "raw"

    async def get(self, kb_id: str, path: str) -> Optional[dict]:
        async with self.db.execute(
            "SELECT * FROM sources WHERE kb_id=? AND path=?", (kb_id, path)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_by_id(self, source_id: str) -> Optional[dict]:
        async with self.db.execute(
            "SELECT * FROM sources WHERE id=?", (source_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    # ── Status ────────────────────────────────────────────────

    async def set_status(self, kb_id: str, path: str, status: str, error: str = "") -> None:
        now = _now()
        if status == "indexed":
            await self.db.execute(
                "UPDATE sources SET status=?, indexed_at=? WHERE kb_id=? AND path=?",
                (status, now, kb_id, path),
            )
        elif status == "extracted":
            await self.db.execute(
                "UPDATE sources SET status=?, extracted_at=? WHERE kb_id=? AND path=?",
                (status, now, kb_id, path),
            )
        else:
            await self.db.execute(
                "UPDATE sources SET status=?, error_log=? WHERE kb_id=? AND path=?",
                (status, error or "", kb_id, path),
            )
        await self.db.commit()

    async def record_wiki_pages(self, kb_id: str, path: str, wiki_paths: list[str]) -> None:
        await self.db.execute(
            "UPDATE sources SET wiki_pages=? WHERE kb_id=? AND path=?",
            (json.dumps(wiki_paths), kb_id, path),
        )
        await self.db.commit()

    # ── Queries ───────────────────────────────────────────────

    async def list_by_kb(self, kb_id: str, status: str = "") -> list[dict]:
        if status:
            async with self.db.execute(
                "SELECT * FROM sources WHERE kb_id=? AND status=? ORDER BY created_at DESC",
                (kb_id, status),
            ) as cursor:
                return [dict(row) async for row in cursor]
        async with self.db.execute(
            "SELECT * FROM sources WHERE kb_id=? ORDER BY created_at DESC", (kb_id,)
        ) as cursor:
            return [dict(row) async for row in cursor]

    async def get_pending(self, kb_id: str) -> list[dict]:
        """Sources that are 'raw' or 'indexed' (ready for extraction)."""
        async with self.db.execute(
            "SELECT * FROM sources WHERE kb_id=? AND status IN ('raw', 'indexed') ORDER BY created_at",
            (kb_id,),
        ) as cursor:
            return [dict(row) async for row in cursor]

    async def get_active(self, kb_id: str) -> list[dict]:
        """Documents currently in queue or processing (not terminal states)."""
        async with self.db.execute(
            "SELECT * FROM sources WHERE kb_id=? AND status NOT IN ('extracted', 'error', 'cancelled') ORDER BY "
            "CASE status WHEN 'extracting' THEN 0 WHEN 'dedup_check' THEN 1 WHEN 'organizing' THEN 2 "
            "WHEN 'indexed' THEN 3 WHEN 'raw' THEN 4 ELSE 5 END, created_at",
            (kb_id,),
        ) as cursor:
            return [dict(row) async for row in cursor]

    async def cancel(self, kb_id: str, path: str) -> bool:
        """Cancel a queued document (raw/indexed only, not mid-processing)."""
        row = await self.get(kb_id, path)
        if not row or row["status"] not in ("raw", "indexed"):
            return False
        await self.set_status(kb_id, path, "cancelled")
        return True

    async def retry(self, kb_id: str, path: str) -> bool:
        """Reset a failed/cancelled document back to raw for re-processing."""
        row = await self.get(kb_id, path)
        if not row or row["status"] not in ("error", "cancelled"):
            return False
        await self.set_status(kb_id, path, "raw")
        return True

    async def get_stats(self, kb_id: str) -> dict:
        async with self.db.execute(
            "SELECT status, COUNT(*) as cnt FROM sources WHERE kb_id=? GROUP BY status",
            (kb_id,),
        ) as cursor:
            stats = {s: 0 for s in STATUSES}
            async for row in cursor:
                stats[row["status"]] = row["cnt"]
            stats["total"] = sum(stats.values())
            return stats

    async def count(self, kb_id: str) -> int:
        async with self.db.execute(
            "SELECT COUNT(*) as cnt FROM sources WHERE kb_id=?", (kb_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row["cnt"] if row else 0

    # ── Reverse lookup ────────────────────────────────────────

    async def find_wiki_pages_for_source(self, kb_id: str, source_path: str) -> list[str]:
        """Get the list of wiki pages generated from this source."""
        row = await self.get(kb_id, source_path)
        if not row:
            return []
        try:
            return json.loads(row.get("wiki_pages", "[]"))
        except json.JSONDecodeError:
            return []

    async def find_sources_referencing_deleted(self, kb_id: str,
                                                deleting_paths: list[str]) -> list[dict]:
        """After source files are deleted, find wiki pages that reference them.
        This queries ALL sources to find wiki_pages that might reference the deleted files.
        """
        affected = []
        for path in deleting_paths:
            wiki_pages = await self.find_wiki_pages_for_source(kb_id, path)
            if wiki_pages:
                affected.append({"source_path": path, "wiki_pages": wiki_pages})
        return affected

    # ── Deletion ──────────────────────────────────────────────

    async def delete(self, kb_id: str, path: str) -> bool:
        cursor = await self.db.execute(
            "DELETE FROM sources WHERE kb_id=? AND path=?", (kb_id, path)
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def delete_batch(self, kb_id: str, paths: list[str]) -> int:
        count = 0
        for p in paths:
            if await self.delete(kb_id, p):
                count += 1
        return count
