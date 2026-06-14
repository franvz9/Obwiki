from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..models import KnowledgeBaseCreate, KnowledgeBaseUpdate
from ..services.kb_registry import KBRegistry
from ..deps import get_registry

router = APIRouter(prefix="/v1/kbs", tags=["kbs"])


@router.post("", status_code=201)
async def create_kb(data: KnowledgeBaseCreate, registry: KBRegistry = Depends(get_registry)):
    kb = await registry.create(data)
    return kb.model_dump()


@router.get("")
async def list_kbs(registry: KBRegistry = Depends(get_registry)):
    kbs = await registry.list_all()
    return [kb.model_dump() for kb in kbs]


# NOTE: /active and /templates must be BEFORE /{kb_id}
@router.get("/active")
async def get_active_kb(registry: KBRegistry = Depends(get_registry)):
    kb = await registry.get_active()
    if kb is None:
        raise HTTPException(404, "no active knowledge base")
    return kb.model_dump()


@router.get("/templates")
async def list_templates():
    from ..services.templates import list_templates as lt
    return lt()


@router.get("/{kb_id}")
async def get_kb(kb_id: str, registry: KBRegistry = Depends(get_registry)):
    kb = await registry.get(kb_id)
    if kb is None:
        raise HTTPException(404, "knowledge base not found")
    return kb.model_dump()


@router.patch("/{kb_id}")
async def update_kb(kb_id: str, data: KnowledgeBaseUpdate, registry: KBRegistry = Depends(get_registry)):
    kb = await registry.update(kb_id, data)
    if kb is None:
        raise HTTPException(404, "knowledge base not found")
    return kb.model_dump()


@router.delete("/{kb_id}")
async def delete_kb(kb_id: str, registry: KBRegistry = Depends(get_registry)):
    deleted = await registry.delete(kb_id)
    if not deleted:
        raise HTTPException(404, "knowledge base not found")
    return {"status": "deleted"}


@router.post("/{kb_id}/initialize")
async def initialize_kb(kb_id: str, template: str = "general",
                         registry: KBRegistry = Depends(get_registry)):
    from ..deps import get_scanner
    result = await registry.initialize(kb_id, template_id=template)
    if "error" in result:
        raise HTTPException(404, result["error"])
    # Auto-scan to index existing wiki pages + inbox files
    try:
        kb = await registry.get(kb_id)
        scanner = await get_scanner()
        scan_r = await scanner.scan_kb(kb_id, kb.root_path)
        result["scan"] = scan_r
    except Exception:
        pass
    return result


@router.post("/{kb_id}/activate")
async def activate_kb(kb_id: str, registry: KBRegistry = Depends(get_registry)):
    kb = await registry.activate(kb_id)
    if kb is None:
        raise HTTPException(404, "knowledge base not found")
    return kb.model_dump()
