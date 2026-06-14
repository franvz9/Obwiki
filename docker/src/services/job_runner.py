from __future__ import annotations

import asyncio
import json
import traceback
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from ..models.job import Job, JobCreate, JobStatus, JobType
from ..config import settings


class JobRunner:
    def __init__(self, db: aiosqlite.Connection, scanner=None, extractor=None,
                 evolver=None, crystallizer=None, linter=None, cleanup=None, community_gen=None,
                 organizer=None, llm=None):
        self.db = db
        self.scanner = scanner
        self.extractor = extractor
        self.evolver = evolver
        self.crystallizer = crystallizer
        self.linter = linter
        self.cleanup = cleanup
        self.community_gen = community_gen
        self.organizer = organizer
        self._llm = llm
        self._sem = asyncio.Semaphore(settings.max_concurrent_jobs)

    async def create(self, kb_id: str, data: JobCreate) -> Job:
        now = _now()
        job = Job(kb_id=kb_id, type=data.type, payload=data.payload, created_at=now)
        await self.db.execute(
            "INSERT INTO jobs (id, kb_id, type, status, payload, progress, created_at, log) "
            "VALUES (?, ?, ?, ?, ?, 0, ?, '')",
            (job.id, job.kb_id, job.type.value, job.status.value,
             json.dumps(job.payload), job.created_at),
        )
        await self.db.commit()
        asyncio.create_task(self._run(job))
        return job

    async def _run(self, job: Job) -> None:
        async with self._sem:
            await self._update_status(job.id, JobStatus.running, started_at=_now(), progress=10)
            try:
                result = await asyncio.wait_for(
                    self._execute(job),
                    timeout=settings.job_timeout_seconds,
                )
                # Mark as failed if result indicates error
                if isinstance(result, str) and any(result.startswith(p) for p in (
                    "LLM_NOT_CONFIGURED", "QUOTA_EXCEEDED", "error:", "scanner not",
                    "extractor not", "evolver not", "crystallizer not", "linter not",
                )):
                    await self._update_status(job.id, JobStatus.failed, progress=100, log=str(result))
                else:
                    await self._update_status(job.id, JobStatus.done, progress=100, log=str(result))
            except asyncio.TimeoutError:
                await self._update_status(job.id, JobStatus.failed, log="timeout")
            except Exception:
                await self._update_status(
                    job.id, JobStatus.failed, log=traceback.format_exc()
                )

    async def _execute(self, job: Job) -> str:
        kb = await self._get_kb_root(job.kb_id)
        if kb is None:
            return "error: kb not found"

        # Token quota + LLM check for LLM-dependent jobs
        token_jobs = {JobType.extract, JobType.evolve, JobType.crystallize, JobType.repair, JobType.process}
        if job.type in token_jobs:
            if await self._check_quota_exceeded():
                return "QUOTA_EXCEEDED: daily token limit reached"
        if job.type in token_jobs:
            # Check if LLM is configured (not using default localhost)
            llm_endpoint = self._llm.endpoint if self._llm else "http://localhost:11434/v1"
            if "localhost" in llm_endpoint or "127.0.0.1" in llm_endpoint:
                return "LLM_NOT_CONFIGURED: 请先在插件「模型供应商」中添加并配置 LLM 服务"

        result: str
        tokens = 0

        match job.type:
            case JobType.scan:
                if self.scanner:
                    r = await self.scanner.scan_kb(job.kb_id, kb)
                    result = f"scan done: {json.dumps(r)}"
                else:
                    return "scanner not available"

            case JobType.process:
                if not self.scanner or not self.extractor:
                    return "scanner or extractor not available"
                # Step 1: scan
                r = await self.scanner.scan_kb(job.kb_id, kb)
                await self._update_status(job.id, JobStatus.running, progress=30, log=f"scan: {json.dumps(r)}")
                # Step 2: organize
                if self.organizer:
                    r2 = await self.organizer.organize(job.kb_id, kb)
                    await self._update_status(job.id, JobStatus.running, progress=50, log=f"organize: {json.dumps(r2)}")
                # Step 3: extract
                r3 = await self.extractor.extract(job.kb_id, kb)
                tokens = r3.get("tokens", 0)
                result = f"process done: scan={json.dumps(r)}, extract={json.dumps(r3, ensure_ascii=False)}"

            case JobType.extract:
                if self.extractor:
                    source_paths = job.payload.get("source_paths")
                    force_text = job.payload.get("force_text", False)
                    r = await self.extractor.extract(job.kb_id, kb, source_paths=source_paths, force_text=force_text)
                    tokens = r.get("tokens", 0)
                    result = f"extract done: {json.dumps(r, ensure_ascii=False)}"
                else:
                    return "extractor not available — configure LLM first"

            case JobType.evolve:
                if self.evolver:
                    scope = job.payload.get("scope", "all")
                    r = await self.evolver.evolve(job.kb_id, kb, scope=scope)
                    tokens = r.get("tokens", 0)
                    result = f"evolve done: {json.dumps(r, ensure_ascii=False)}"
                else:
                    return "evolver not available — configure LLM first"

            case JobType.crystallize:
                if self.crystallizer:
                    topic = job.payload.get("topic", "")
                    r = await self.crystallizer.crystallize(job.kb_id, kb, topic=topic)
                    tokens = r.get("tokens", 0)
                    result = f"crystallize done: {json.dumps(r, ensure_ascii=False)}"
                    # Auto-detect merge candidates (skip if cached)
                    if "cached" not in str(r.get("status", "")):
                        md_tokens = await self._run_merge_detect(job.kb_id, kb)
                        tokens += md_tokens
                else:
                    return "crystallizer not available — configure LLM first"

            case JobType.repair:
                if self.linter:
                    auto_fix = job.payload.get("auto_fix", False)
                    r = await self.linter.lint(job.kb_id, kb, auto_fix=auto_fix)
                    tokens = r.get("tokens", 0)
                    result = f"lint/repair done: {json.dumps(r, ensure_ascii=False)}"
                else:
                    return "linter not available — configure LLM first"

            case JobType.communities:
                if self.community_gen:
                    r = await self.community_gen.generate(job.kb_id, kb)
                    result = f"communities done: {json.dumps(r, ensure_ascii=False)}"
                    if "cached" not in str(r.get("status", "")):
                        md_tokens = await self._run_merge_detect(job.kb_id, kb)
                        tokens += md_tokens
                else:
                    return "community generator not available"

            case JobType.organize:
                if self.organizer:
                    r = await self.organizer.organize(job.kb_id, kb)
                    result = f"organize done: {json.dumps(r, ensure_ascii=False)}"
                else:
                    return "organizer not available"

        # Record token count + daily usage
        if tokens > 0:
            await self.db.execute("UPDATE jobs SET token_count = ? WHERE id = ?", (tokens, job.id))
            await self._record_token_usage(job.kb_id, tokens)
            await self.db.commit()

        return result

    async def _check_quota_exceeded(self) -> bool:
        """Check if daily global token quota is exceeded."""
        from datetime import date
        today = date.today().isoformat()
        quota = await self._get_quota()
        if quota <= 0:
            return False
        async with self.db.execute(
            "SELECT tokens_used FROM token_usage WHERE date=?", (today,)
        ) as cursor:
            row = await cursor.fetchone()
            used = row[0] if row else 0
            return used >= quota

    async def _get_quota(self) -> int:
        async with self.db.execute(
            "SELECT value FROM config WHERE key='token_quota_global'"
        ) as cursor:
            row = await cursor.fetchone()
            return int(row[0]) if row else 0

    async def _run_merge_detect(self, kb_id: str, kb_root: str) -> int:
        """Auto-detect merge candidates after crystallize/community gen. Returns tokens used."""
        try:
            from .merge_detector import MergeDetector
            detector = MergeDetector(self.db, llm=self._llm)
            result = await detector.detect_and_merge(kb_id, kb_root)
            return detector.tokens_used
        except Exception:
            return 0  # best-effort, don't fail the main job

    async def _record_token_usage(self, kb_id: str, tokens: int) -> None:
        from datetime import date
        today = date.today().isoformat()
        await self.db.execute(
            """INSERT INTO token_usage (date, tokens_used) VALUES (?, ?)
               ON CONFLICT(date) DO UPDATE SET tokens_used = tokens_used + ?""",
            (today, tokens, tokens),
        )

    async def get(self, job_id: str) -> Optional[Job]:
        async with self.db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return _row_to_job(row)

    async def list_by_kb(self, kb_id: str, limit: int = 50) -> list[Job]:
        async with self.db.execute(
            "SELECT * FROM jobs WHERE kb_id = ? ORDER BY created_at DESC LIMIT ?",
            (kb_id, limit),
        ) as cursor:
            return [_row_to_job(row) async for row in cursor]

    async def _update_status(self, job_id: str, status: JobStatus, **kwargs) -> None:
        parts = ["status = ?"]
        values = [status.value]
        for k, v in kwargs.items():
            parts.append(f"{k} = ?")
            values.append(v)
        # Auto-set finished_at for terminal states
        if status in (JobStatus.done, JobStatus.failed):
            parts.append("finished_at = ?")
            values.append(_now())
        values.append(job_id)
        await self.db.execute(
            f"UPDATE jobs SET {', '.join(parts)} WHERE id = ?", values
        )
        await self.db.commit()

    async def _get_kb_root(self, kb_id: str) -> Optional[str]:
        async with self.db.execute(
            "SELECT root_path FROM knowledge_bases WHERE id = ?", (kb_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row["root_path"] if row else None


def _now() -> str:
    return datetime.now().isoformat()


def _row_to_job(row) -> Job:
    d = dict(row)
    d["payload"] = json.loads(d.get("payload", "{}"))
    return Job.model_validate(d)
