"""Provider configuration management — store, query, and detect models from endpoints."""

from __future__ import annotations

import json
import uuid
from typing import Optional

import aiosqlite
import httpx


class ProviderService:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def list_all(self) -> list[dict]:
        async with self.db.execute("SELECT * FROM provider_configs ORDER BY created_at") as cur:
            rows = [dict(r) async for r in cur]
        for r in rows:
            r["models"] = _normalize_models(json.loads(r.get("models", "[]")))
            r["is_default_text"] = bool(r.get("is_default_text", 0))
            r["is_default_vision"] = bool(r.get("is_default_vision", 0))
        return rows

    async def get(self, pid: str) -> Optional[dict]:
        async with self.db.execute("SELECT * FROM provider_configs WHERE id=?", (pid,)) as cur:
            r = await cur.fetchone()
        if r is None: return None
        d = dict(r)
        d["models"] = _normalize_models(json.loads(d.get("models", "[]")))
        d["is_default_text"] = bool(d.get("is_default_text", 0))
        d["is_default_vision"] = bool(d.get("is_default_vision", 0))
        return d

    async def save(self, data: dict) -> dict:
        pid = data.get("id") or uuid.uuid4().hex[:12]
        existing = await self.get(pid)
        if existing:
            await self.db.execute(
                """UPDATE provider_configs SET name=?, provider=?, endpoint=?, api_key=?, models=?
                   WHERE id=?""",
                (data["name"], data["provider"], data["endpoint"], data.get("api_key",""),
                 json.dumps(data.get("models",[])), pid),
            )
        else:
            await self.db.execute(
                """INSERT INTO provider_configs (id, name, provider, endpoint, api_key, models)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (pid, data["name"], data["provider"], data["endpoint"],
                 data.get("api_key",""), json.dumps(data.get("models",[]))),
            )
        await self.db.commit()
        return await self.get(pid) or {"id": pid}

    async def set_default(self, pid: str, kind: str) -> dict:
        """Set a provider as default for 'text' or 'vision'."""
        col = "is_default_text" if kind == "text" else "is_default_vision"
        await self.db.execute(f"UPDATE provider_configs SET {col}=0")
        await self.db.execute(f"UPDATE provider_configs SET {col}=1 WHERE id=?", (pid,))
        await self.db.commit()
        return await self.get(pid) or {"id": pid}

    async def delete(self, pid: str) -> bool:
        c = await self.db.execute("DELETE FROM provider_configs WHERE id=?", (pid,))
        await self.db.commit()
        return c.rowcount > 0

    async def get_default_text(self) -> Optional[dict]:
        async with self.db.execute(
            "SELECT * FROM provider_configs WHERE is_default_text=1 LIMIT 1"
        ) as cur:
            r = await cur.fetchone()
        if r is None:
            # Fallback to first provider
            async with self.db.execute("SELECT * FROM provider_configs LIMIT 1") as cur:
                r = await cur.fetchone()
        if r is None: return None
        d = dict(r)
        d["models"] = json.loads(d.get("models", "[]"))
        return d

    async def get_default_vision(self) -> Optional[dict]:
        async with self.db.execute(
            "SELECT * FROM provider_configs WHERE is_default_vision=1 LIMIT 1"
        ) as cur:
            r = await cur.fetchone()
        if r is None: return None
        d = dict(r)
        d["models"] = json.loads(d.get("models", "[]"))
        return d


def _normalize_models(raw: list) -> list[dict]:
    """Convert legacy string models to {id, vision, reasoning, tools, search} format."""
    from .model_registry import lookup
    result = []
    for item in raw:
        if isinstance(item, str):
            spec = lookup(item)
            result.append({
                "id": item, "vision": spec.vision,
                "reasoning": False, "tools": False, "search": False,
            })
        elif isinstance(item, dict):
            result.append({
                "id": item.get("id", ""),
                "vision": item.get("vision", False),
                "reasoning": item.get("reasoning", False),
                "tools": item.get("tools", False),
                "search": item.get("search", False),
            })
    return result


async def detect_models(endpoint: str, api_key: str = "", provider: str = "openai") -> dict:
    """Detect available models from a provider endpoint. Returns {models: [...], error: ...}."""
    try:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        base = endpoint.rstrip("/").replace("/chat/completions", "").replace("/v1", "")
        url = f"{base}/v1/models"

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return {"models": [], "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}

            data = resp.json()
            raw_models = data.get("data", data.get("models", []))
            models = []
            for m in raw_models:
                mid = m.get("id", "") if isinstance(m, dict) else str(m)
                if mid and not mid.startswith("ft:") and "embedding" not in mid.lower():
                    models.append({"id": mid, "owned_by": m.get("owned_by","") if isinstance(m,dict) else ""})
            return {"models": models, "count": len(models)}
    except Exception as e:
        return {"models": [], "error": str(e)[:200]}
