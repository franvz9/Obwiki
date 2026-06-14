from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routes import kbs, files, jobs, dashboard, providers


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure db is initialized
    from .deps import get_db_conn, get_runner
    from .services.scheduler import JobScheduler
    db = await get_db_conn()
    runner = await get_runner()
    scheduler = JobScheduler(db, runner=runner)
    await scheduler.start()
    app.state.scheduler = scheduler
    yield
    await scheduler.stop()


from fastapi import Request
import time

app = FastAPI(
    title="LLMWiki API",
    version="0.2.0",
    description="LLM-driven local knowledge engine",
    lifespan=lifespan,
)

# Increase max upload size to 200MB for large PDFs
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.datastructures import UploadFile
app.state.max_upload_size = 200 * 1024 * 1024

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(kbs.router)
app.include_router(files.router)
app.include_router(jobs.router)
app.include_router(dashboard.router)
app.include_router(providers.router)

# MCP server runs as separate process via CMD override
# (SSE ASGI not compatible with FastAPI mount)


@app.get("/v1/config")
async def get_config():
    """Server-level config for clients to auto-discover."""
    from .config import settings
    return {
        "kb_root": str(settings.kb_root),
        "port": settings.port,
        "version": "0.1.0",
    }


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.2.0"}


@app.get("/health/llm")
async def health_llm():
    """Check if LLM is configured and reachable. Returns model capabilities."""
    from .services.llm import LLMClient
    from .services.model_registry import lookup
    llm = LLMClient()
    spec = lookup(llm.model) if llm.model else None
    result = {
        "configured": bool(llm.api_key or "localhost" not in llm.endpoint),
        "endpoint": llm.endpoint,
        "model": llm.model,
        "provider": llm.provider_name,
        "context_window": spec.context_window if spec else 8192,
        "max_output": spec.max_output if spec else 4096,
        "vision": spec.vision if spec else False,
    }
    try:
        test = await llm.chat(
            [{"role": "user", "content": "Say 'ok' and nothing else."}],
            max_tokens=5, temperature=0,
        )
        result["reachable"] = True
    except Exception as e:
        result["reachable"] = False
        result["error"] = str(e)[:200]
    return result
