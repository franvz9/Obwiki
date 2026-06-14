from __future__ import annotations

import aiosqlite

from .db import get_db
from .services.kb_registry import KBRegistry
from .services.source_registry import SourceRegistry
from .services.wiki_schema import WikiSchema
from .services.scanner import Scanner
from .services.job_runner import JobRunner
from .services.llm import LLMClient
from .services.extractor import Extractor
from .services.evolver import Evolver
from .services.crystallizer import Crystallizer
from .services.linter import Linter
from .services.source_cleanup import SourceCleanup
from .services.community_gen import CommunityGenerator
from .services.organizer import Organizer

_registry: KBRegistry | None = None
_source_registry: SourceRegistry | None = None
_scanner: Scanner | None = None
_runner: JobRunner | None = None
_db: aiosqlite.Connection | None = None
_llm: LLMClient | None = None
_cleanup: SourceCleanup | None = None


async def get_db_conn():
    global _db
    if _db is None:
        _db = await get_db()
    return _db


async def get_registry():
    global _registry
    if _registry is None:
        db = await get_db_conn()
        _registry = KBRegistry(db)
    return _registry


async def get_source_registry():
    global _source_registry
    if _source_registry is None:
        db = await get_db_conn()
        _source_registry = SourceRegistry(db)
    return _source_registry


async def get_scanner():
    global _scanner
    if _scanner is None:
        db = await get_db_conn()
        sr = await get_source_registry()
        _scanner = Scanner(db, sr)
    return _scanner


async def get_llm():
    global _llm
    if _llm is None:
        db = await get_db_conn()
        _llm = await _resolve_llm(db)
    return _llm


async def _resolve_llm(db):
    """Resolve LLM client from database provider configs, falling back to env settings."""
    import json
    from .config import settings

    async with db.execute(
        "SELECT * FROM provider_configs WHERE is_default_text = 1 LIMIT 1"
    ) as cur:
        row = await cur.fetchone()

    if row:
        d = dict(row)
        ep = d["endpoint"]
        models = json.loads(d.get("models", "[]"))
        model = models[0]["id"] if models else settings.llm_model
        provider = d.get("provider", "openai")
        api_key = d.get("api_key", "") or settings.llm_api_key or ""

        # Strip trailing slash from endpoint
        ep = ep.rstrip("/")
        return LLMClient(endpoint=ep, model=model, api_key=api_key, provider=provider)

    return LLMClient()


async def get_cleanup():
    global _cleanup
    if _cleanup is None:
        db = await get_db_conn()
        sr = await get_source_registry()
        _cleanup = SourceCleanup(db, sr)
    return _cleanup


async def get_runner():
    global _runner
    if _runner is None:
        db = await get_db_conn()
        scanner = await get_scanner()
        llm = await get_llm()
        sr = await get_source_registry()
        cleanup = await get_cleanup()
        extractor = Extractor(db, llm, sr)
        evolver = Evolver(db, llm)
        crystallizer = Crystallizer(db, llm)
        linter = Linter(db, llm)
        community_gen = CommunityGenerator(db)
        organizer = Organizer(db)
        _runner = JobRunner(
            db, scanner=scanner, extractor=extractor,
            evolver=evolver, crystallizer=crystallizer, linter=linter,
            cleanup=cleanup, community_gen=community_gen, organizer=organizer,
            llm=llm,
        )
    return _runner
