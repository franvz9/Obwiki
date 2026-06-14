from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..models.job import JobCreate
from ..services.job_runner import JobRunner
from ..services.kb_registry import KBRegistry
from ..deps import get_registry, get_runner

router = APIRouter(prefix="/v1", tags=["jobs"])


async def _create_job(kb_id: str, job_type: str, payload: dict,
                      registry: KBRegistry, runner: JobRunner):
    kb = await registry.get(kb_id)
    if kb is None:
        raise HTTPException(404, "knowledge base not found")
    job_create = JobCreate(type=job_type, payload=payload)
    job = await runner.create(kb_id, job_create)
    return job.model_dump()


@router.post("/kbs/{kb_id}/jobs/scan", status_code=201)
async def create_scan_job(kb_id: str, registry=Depends(get_registry), runner=Depends(get_runner)):
    return await _create_job(kb_id, "scan", {}, registry, runner)


@router.post("/kbs/{kb_id}/jobs/process", status_code=201)
async def create_process_job(kb_id: str, registry=Depends(get_registry), runner=Depends(get_runner)):
    return await _create_job(kb_id, "process", {}, registry, runner)


@router.post("/kbs/{kb_id}/jobs/extract", status_code=201)
async def create_extract_job(kb_id: str, registry=Depends(get_registry), runner=Depends(get_runner)):
    return await _create_job(kb_id, "extract", {}, registry, runner)


@router.post("/kbs/{kb_id}/jobs/evolve", status_code=201)
async def create_evolve_job(kb_id: str, registry=Depends(get_registry), runner=Depends(get_runner)):
    return await _create_job(kb_id, "evolve", {}, registry, runner)


@router.post("/kbs/{kb_id}/jobs/crystallize", status_code=201)
async def create_crystallize_job(kb_id: str, registry=Depends(get_registry), runner=Depends(get_runner)):
    return await _create_job(kb_id, "crystallize", {}, registry, runner)


@router.post("/kbs/{kb_id}/jobs/lint", status_code=201)
async def create_lint_job(
    kb_id: str,
    auto_fix: bool = False,
    registry=Depends(get_registry),
    runner=Depends(get_runner),
):
    return await _create_job(kb_id, "repair", {"auto_fix": auto_fix}, registry, runner)


@router.post("/kbs/{kb_id}/jobs/communities", status_code=201)
async def create_communities_job(kb_id: str, registry=Depends(get_registry), runner=Depends(get_runner)):
    return await _create_job(kb_id, "communities", {}, registry, runner)


@router.post("/kbs/{kb_id}/jobs/organize", status_code=201)
async def create_organize_job(kb_id: str, registry=Depends(get_registry), runner=Depends(get_runner)):
    return await _create_job(kb_id, "organize", {}, registry, runner)


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, runner: JobRunner = Depends(get_runner)):
    job = await runner.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job.model_dump()


@router.get("/kbs/{kb_id}/jobs")
async def list_jobs(kb_id: str, limit: int = 50, runner: JobRunner = Depends(get_runner)):
    jobs = await runner.list_by_kb(kb_id, limit=limit)
    return [j.model_dump() for j in jobs]
