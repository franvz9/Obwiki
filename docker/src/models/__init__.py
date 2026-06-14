from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class KBStatus(str, Enum):
    active = "active"
    idle = "idle"
    error = "error"


class KBConfig(BaseModel):
    llm_model: str = ""
    llm_endpoint: str = ""
    extract_rules: dict = Field(default_factory=dict)
    evolve_rules: dict = Field(default_factory=dict)
    schedule: dict = Field(default_factory=dict)


class KnowledgeBase(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    root_path: str
    status: KBStatus = KBStatus.idle
    config: KBConfig = Field(default_factory=KBConfig)
    created_at: str = ""
    updated_at: str = ""


class KnowledgeBaseCreate(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    root_path: str


class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = None
    config: Optional[KBConfig] = None
