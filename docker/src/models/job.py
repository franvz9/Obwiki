from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class JobType(str, Enum):
    scan = "scan"
    index = "index"
    extract = "extract"
    evolve = "evolve"
    crystallize = "crystallize"
    communities = "communities"
    organize = "organize"
    repair = "repair"
    process = "process"  # scan → organize → extract pipeline


class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class Job(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    kb_id: str
    type: JobType
    status: JobStatus = JobStatus.pending
    payload: dict = Field(default_factory=dict)
    progress: int = 0
    token_count: int = 0
    created_at: str = ""
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    log: str = ""


class JobCreate(BaseModel):
    type: JobType
    payload: dict = Field(default_factory=dict)
