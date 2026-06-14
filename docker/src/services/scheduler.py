"""Background job scheduler — fires automated jobs on a schedule + debounced wiki-change trigger.

Schedule config stored in config table as JSON keyed by schedule_{kb_id}.
Auto-evolution: detects wiki changes → waits 10 min cooldown → if no new changes, triggers evolve→crystallize→communities.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Optional

import aiosqlite


class JobScheduler:
    def __init__(self, db: aiosqlite.Connection, runner=None):
        self.db = db
        self.runner = runner
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the scheduler loop."""
        if self._task:
            return
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
            self._task = None

    async def _loop(self):
        """Check schedule every 60 seconds and fire jobs as needed."""
        while True:
            try:
                await self._tick()
            except Exception:
                pass
            await asyncio.sleep(60)

    async def _tick(self):
        """Check all KBs for due scheduled tasks + wiki change debounce."""
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        weekday = str(now.weekday())  # 0=Monday

        async with self.db.execute("SELECT id, root_path FROM knowledge_bases") as cursor:
            kbs = [{"id": row["id"], "root": row["root_path"]} async for row in cursor]

        for kb in kbs:
            kb_id = kb["id"]

            # ── Scheduled tasks ──
            schedule = await self._get_schedule(kb_id)
            if schedule:
                last_runs = await self._get_last_runs(kb_id)
                for task_key, task_config in schedule.items():
                    if not task_config.get("enabled"):
                        continue
                    cron = task_config.get("cron", "off")
                    if cron == "off":
                        continue
                    task_time = task_config.get("time", "03:00")
                    if now.strftime("%H:%M") != task_time:
                        continue
                    if cron == "daily":
                        if last_runs.get(task_key) == today:
                            continue
                    elif cron == "weekly":
                        task_day = task_config.get("day", "1")
                        if weekday != task_day:
                            continue
                        if last_runs.get(task_key) == today:
                            continue
                    await self._fire(kb_id, task_key)
                    await self._record_run(kb_id, task_key, today)

            # ── Wiki change debounce → auto-evolution ──
            await self._check_wiki_changes(kb_id, kb["root"], now, today)

    async def _fire(self, kb_id: str, task_key: str):
        """Fire a scheduled task. task_key maps to a sequence of jobs."""
        if not self.runner:
            return

        from ..models.job import JobCreate
        today = datetime.now().isoformat()

        if task_key == "organize":
            job = await self.runner.create(kb_id, JobCreate(type="organize", payload={}))
        elif task_key == "process":
            job = await self.runner.create(kb_id, JobCreate(type="process", payload={}))
        elif task_key == "evolve":
            # evolve → crystallize → communities
            job = await self.runner.create(kb_id, JobCreate(type="evolve", payload={}))
            await asyncio.sleep(5)  # let it start
            # These will queue behind evolve via semaphore
            await self.runner.create(kb_id, JobCreate(type="crystallize", payload={}))
            await self.runner.create(kb_id, JobCreate(type="communities", payload={}))
        elif task_key == "lint":
            job = await self.runner.create(kb_id, JobCreate(type="repair", payload={"auto_fix": True}))

    async def _get_schedule(self, kb_id: str) -> dict:
        async with self.db.execute(
            "SELECT value FROM config WHERE key=?", (f"schedule_{kb_id}",)
        ) as cur:
            row = await cur.fetchone()
            return json.loads(row[0]) if row else {}

    async def _get_last_runs(self, kb_id: str) -> dict:
        async with self.db.execute(
            "SELECT value FROM config WHERE key=?", (f"schedule_runs_{kb_id}",)
        ) as cur:
            row = await cur.fetchone()
            return json.loads(row[0]) if row else {}

    async def _record_run(self, kb_id: str, task_key: str, today: str):
        runs = await self._get_last_runs(kb_id)
        runs[task_key] = today
        await self.db.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            (f"schedule_runs_{kb_id}", json.dumps(runs)),
        )
        await self.db.commit()

    # ── Wiki change debounce ──

    async def _check_wiki_changes(self, kb_id: str, root_path: str, now, today: str):
        """Detect wiki structure changes and trigger auto-evolution after cooldown."""
        from pathlib import Path
        import hashlib

        root = Path(root_path)
        wiki_dir = root / "wiki"
        if not wiki_dir.exists():
            return

        # Compute fingerprint of wiki pages (paths + sizes, excluding crystals)
        pages = []
        for md_file in wiki_dir.rglob("*.md"):
            if "crystals" in str(md_file.relative_to(wiki_dir)).replace("\\", "/").split("/"):
                continue
            try:
                pages.append(f"{md_file.relative_to(root)}:{md_file.stat().st_size}")
            except Exception:
                pass

        if not pages:
            return

        fp = hashlib.sha256("|".join(sorted(pages)).encode()).hexdigest()[:16]
        cooldown_minutes = 10

        # Read stored state
        stored_fp = ""
        change_ts = ""
        last_trigger = ""
        async with self.db.execute(
            "SELECT value FROM config WHERE key=?", (f"wiki_watch_{kb_id}",)
        ) as cur:
            row = await cur.fetchone()
            if row:
                state = json.loads(row[0])
                stored_fp = state.get("fp", "")
                change_ts = state.get("change_ts", "")
                last_trigger = state.get("last_trigger", "")

        # New state to save
        new_state = {"fp": stored_fp, "change_ts": change_ts, "last_trigger": last_trigger}

        if fp != stored_fp:
            # Wiki changed — start/reset cooldown
            new_state["fp"] = fp
            new_state["change_ts"] = now.isoformat()
        elif change_ts and last_trigger != change_ts:
            # No new changes since cooldown started — check if cooldown expired
            try:
                change_dt = datetime.fromisoformat(change_ts)
                elapsed = (now - change_dt).total_seconds() / 60
                if elapsed >= cooldown_minutes:
                    # Trigger auto-evolution
                    if self.runner:
                        await self._fire_auto_evolve(kb_id)
                    new_state["last_trigger"] = change_ts
                    new_state["change_ts"] = ""  # clear cooldown
            except Exception:
                pass

        await self.db.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            (f"wiki_watch_{kb_id}", json.dumps(new_state)),
        )
        await self.db.commit()

    async def _fire_auto_evolve(self, kb_id: str):
        """Trigger auto-evolution: evolve → crystallize → communities."""
        from ..models.job import JobCreate
        await self.runner.create(kb_id, JobCreate(type="evolve", payload={}))
        await asyncio.sleep(5)
        await self.runner.create(kb_id, JobCreate(type="crystallize", payload={}))
        await self.runner.create(kb_id, JobCreate(type="communities", payload={}))
