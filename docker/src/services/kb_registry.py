from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

from ..models import KnowledgeBase, KnowledgeBaseCreate, KnowledgeBaseUpdate, KBStatus


from ..paths import INBOX_DIR, META_DIR, WIKI_DIR, COMMUNITIES_DIR, LLMWIKI_DIR, OPS_DIR, WIKI_SUBDIRS

STD_DIRS = [INBOX_DIR, META_DIR, WIKI_DIR, COMMUNITIES_DIR, OPS_DIR, LLMWIKI_DIR]
CONFIG_YAML = f"{LLMWIKI_DIR}/config.yaml"


class KBRegistry:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def create(self, data: KnowledgeBaseCreate) -> KnowledgeBase:
        now = _now()
        await self.db.execute(
            "INSERT INTO knowledge_bases (id, name, root_path, status, config, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (data.id, data.name, str(data.root_path), KBStatus.idle.value, "{}", now, now),
        )
        await self.db.commit()
        return await self.get(data.id)

    async def get(self, kb_id: str) -> Optional[KnowledgeBase]:
        async with self.db.execute(
            "SELECT * FROM knowledge_bases WHERE id = ?", (kb_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return _row_to_kb(row)

    async def list_all(self) -> list[KnowledgeBase]:
        async with self.db.execute("SELECT * FROM knowledge_bases ORDER BY created_at DESC") as cursor:
            return [_row_to_kb(row) async for row in cursor]

    async def update(self, kb_id: str, data: KnowledgeBaseUpdate) -> Optional[KnowledgeBase]:
        kb = await self.get(kb_id)
        if kb is None:
            return None
        if data.name is not None:
            kb.name = data.name
        if data.config is not None:
            kb.config = data.config
        now = _now()
        await self.db.execute(
            "UPDATE knowledge_bases SET name = ?, config = ?, updated_at = ? WHERE id = ?",
            (kb.name, kb.config.model_dump_json(), now, kb_id),
        )
        await self.db.commit()
        return await self.get(kb_id)

    async def delete(self, kb_id: str) -> bool:
        cursor = await self.db.execute("DELETE FROM knowledge_bases WHERE id = ?", (kb_id,))
        await self.db.commit()
        return cursor.rowcount > 0

    async def initialize(self, kb_id: str, template_id: str = "general") -> dict:
        kb = await self.get(kb_id)
        if kb is None:
            return {"error": "knowledge base not found"}

        root = Path(kb.root_path)
        created = []
        existed = []
        for d in STD_DIRS:
            p = root / d
            if not p.exists():
                p.mkdir(parents=True)
                created.append(str(p))
            else:
                existed.append(str(p))
        # Create wiki subdirectories
        wiki_root = root / WIKI_DIR
        for sub in WIKI_SUBDIRS:
            p = wiki_root / sub
            if not p.exists():
                p.mkdir(parents=True)
                created.append(str(p))

        # Write config.yaml in .llmwiki/ (engine config stays there)
        config_path = root / CONFIG_YAML
        if not config_path.exists():
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("llm_model: ''\nllm_endpoint: ''\nextract_rules: {}\nevolve_rules: {}\nschedule: {}\n")
            created.append(str(config_path))

        # Write schema.md + purpose.md from template into _meta/
        from .templates import get_template, TEMPLATES
        template = get_template(template_id)
        if template is None:
            template = TEMPLATES[0]

        meta_dir = root / META_DIR
        schema_path = meta_dir / "schema.md"
        if not schema_path.exists():
            schema_path.write_text(template.schema_md, encoding="utf-8")
            created.append(str(schema_path))

        purpose_path = meta_dir / "purpose.md"
        if not purpose_path.exists():
            purpose_path.write_text(f"# Purpose\n\n{template.purpose}\n", encoding="utf-8")
            created.append(str(purpose_path))

        # Create extra directories from template
        for extra_dir in template.extra_dirs:
            d = root / extra_dir
            if not d.exists():
                d.mkdir(parents=True)
                created.append(str(d))

        await self.db.execute(
            "UPDATE knowledge_bases SET status = ?, updated_at = ? WHERE id = ?",
            (KBStatus.active.value, _now(), kb_id),
        )
        await self.db.commit()
        return {"created": created, "existed": existed, "template": template_id}

    async def activate(self, kb_id: str) -> Optional[KnowledgeBase]:
        kb = await self.get(kb_id)
        if kb is None:
            return None
        await self.db.execute(
            "UPDATE knowledge_bases SET status = ? WHERE id != ?",
            (KBStatus.idle.value, kb_id),
        )
        await self.db.execute(
            "UPDATE knowledge_bases SET status = ?, updated_at = ? WHERE id = ?",
            (KBStatus.active.value, _now(), kb_id),
        )
        await self.db.commit()
        return await self.get(kb_id)

    async def get_active(self) -> Optional[KnowledgeBase]:
        async with self.db.execute(
            "SELECT * FROM knowledge_bases WHERE status = ?", (KBStatus.active.value,)
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return _row_to_kb(row)


def _now() -> str:
    return datetime.now().isoformat()


def _row_to_kb(row) -> KnowledgeBase:
    d = dict(row)
    from ..models import KBConfig
    d["config"] = KBConfig.model_validate(json.loads(d.get("config", "{}")))
    return KnowledgeBase.model_validate(d)
