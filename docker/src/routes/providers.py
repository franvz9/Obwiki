"""Provider management routes — CRUD + model detection."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..deps import get_db_conn

router = APIRouter(prefix="/v1/providers", tags=["providers"])


class ProviderSave(BaseModel):
    id: str = ""
    name: str = ""
    provider: str = "openai"
    endpoint: str = ""
    api_key: str = ""
    models: list = []  # list of str (legacy) or list of {id, vision, reasoning, tools, search}


class DetectRequest(BaseModel):
    endpoint: str
    api_key: str = ""
    provider: str = "openai"


async def _get_service():
    from ..services.provider_service import ProviderService
    db = await get_db_conn()
    return ProviderService(db)


@router.get("")
async def list_providers():
    svc = await _get_service()
    return await svc.list_all()


@router.post("")
async def save_provider(data: ProviderSave):
    svc = await _get_service()
    return await svc.save(data.model_dump())


@router.delete("/{pid}")
async def delete_provider(pid: str):
    svc = await _get_service()
    ok = await svc.delete(pid)
    if not ok: raise HTTPException(404, "not found")
    return {"status": "deleted"}


@router.post("/{pid}/default/{kind}")
async def set_default(pid: str, kind: str):
    svc = await _get_service()
    if kind == "clear":
        svc_db = await get_db_conn()
        await svc_db.execute("UPDATE provider_configs SET is_default_vision=0")
        await svc_db.commit()
        return {"status": "cleared"}
    return await svc.set_default(pid, kind)


@router.post("/detect")
async def detect_models_route(data: DetectRequest):
    from ..services.provider_service import detect_models
    return await detect_models(data.endpoint, data.api_key, data.provider)
