from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from ..services.kb_registry import KBRegistry
from ..services.wiki_schema import find_wiki_dir
from ..services.source_registry import SourceRegistry
from ..services.job_runner import JobRunner
from ..deps import get_registry, get_source_registry, get_runner, get_db_conn

router = APIRouter(prefix="/v1/kbs/{kb_id}", tags=["dashboard"])


@router.get("/dashboard")
async def get_dashboard(
    kb_id: str,
    registry: KBRegistry = Depends(get_registry),
    sr: SourceRegistry = Depends(get_source_registry),
    runner: JobRunner = Depends(get_runner),
    db=Depends(get_db_conn),
):
    kb = await registry.get(kb_id)
    if kb is None:
        raise HTTPException(404, "knowledge base not found")

    root = Path(kb.root_path)

    # Source stats from SourceRegistry
    source_stats = await sr.get_stats(kb_id)

    # Job stats
    async with db.execute(
        "SELECT status, COUNT(*) as cnt FROM jobs WHERE kb_id = ? GROUP BY status",
        (kb_id,),
    ) as cursor:
        job_stats = {row["status"]: row["cnt"] async for row in cursor}

    # Wiki counts
    wiki_dir = find_wiki_dir(root)
    wiki_count = 0
    if wiki_dir.exists():
        wiki_count = len(list(wiki_dir.rglob("*.md")))

    # Crystal count
    crystals_dir = wiki_dir / "crystals"
    crystal_count = 0
    if crystals_dir.exists():
        crystal_count = len(list(crystals_dir.rglob("*.md")))

    # Graph stats
    graph_edges = 0
    graph_clusters = 0
    edges_path = root / ".llmwiki" / "graph" / "edges.json"
    if edges_path.exists():
        try:
            graph_edges = len(json.loads(edges_path.read_text()))
        except Exception:
            pass
    clusters_path = root / ".llmwiki" / "graph" / "clusters.json"
    if clusters_path.exists():
        try:
            graph_clusters = len(json.loads(clusters_path.read_text()))
        except Exception:
            pass

    return {
        "source": source_stats,
        "wiki": {"total": wiki_count},
        "crystals": {"total": crystal_count},
        "graph": {"edges": graph_edges, "clusters": graph_clusters},
        "jobs": {
            "pending": job_stats.get("pending", 0),
            "running": job_stats.get("running", 0),
            "done": job_stats.get("done", 0),
            "failed": job_stats.get("failed", 0),
        },
        "name": kb.name,
        "status": kb.status.value,
    }


@router.get("/crystals")
async def get_crystals(kb_id: str, registry: KBRegistry = Depends(get_registry)):
    kb = await registry.get(kb_id)
    if kb is None:
        raise HTTPException(404, "knowledge base not found")

    crystals_dir = find_wiki_dir(Path(kb.root_path)) / "crystals" if find_wiki_dir(Path(kb.root_path)) else Path(kb.root_path) / "wiki" / "crystals"
    if not crystals_dir.exists():
        return []

    crystals = []
    for md_file in crystals_dir.rglob("*.md"):
        try:
            text = md_file.read_text(encoding="utf-8")
            crystals.append({
                "path": str(md_file.relative_to(kb.root_path)),
                "title": md_file.stem,
                "preview": text[:500],
            })
        except Exception:
            continue
    return crystals


@router.get("/graph")
async def get_graph(kb_id: str, registry: KBRegistry = Depends(get_registry)):
    kb = await registry.get(kb_id)
    if kb is None:
        raise HTTPException(404, "knowledge base not found")

    edges_path = Path(kb.root_path) / ".llmwiki" / "graph" / "edges.json"
    clusters_path = Path(kb.root_path) / ".llmwiki" / "graph" / "clusters.json"
    gaps_path = Path(kb.root_path) / ".llmwiki" / "graph" / "gaps.json"

    edges = []
    clusters = []
    gaps = []

    if edges_path.exists():
        try:
            edges = json.loads(edges_path.read_text())
        except Exception:
            pass
    if clusters_path.exists():
        try:
            clusters = json.loads(clusters_path.read_text())
        except Exception:
            pass
    if gaps_path.exists():
        try:
            gaps = json.loads(gaps_path.read_text())
        except Exception:
            pass

    return {"edges": edges, "clusters": clusters, "gaps": gaps}


@router.get("/events")
async def get_events(kb_id: str, runner: JobRunner = Depends(get_runner)):
    jobs = await runner.list_by_kb(kb_id)
    return [j.model_dump() for j in jobs[:50]]


async def _get_cleanup():
    from ..deps import get_cleanup
    return await get_cleanup()


@router.get("/sources")
async def list_sources(
    kb_id: str,
    status: str = "",
    registry: KBRegistry = Depends(get_registry),
    sr: SourceRegistry = Depends(get_source_registry),
):
    """List source files with optional status filter (raw|indexed|extracted|error)."""
    kb = await registry.get(kb_id)
    if kb is None:
        raise HTTPException(404, "knowledge base not found")
    return await sr.list_by_kb(kb_id, status)


@router.delete("/sources/{path:path}")
async def delete_source(
    kb_id: str,
    path: str,
    registry: KBRegistry = Depends(get_registry),
    cleanup: "SourceCleanup" = Depends(_get_cleanup),
):
    """Delete a source file and cascade-clean wiki pages."""
    kb = await registry.get(kb_id)
    if kb is None:
        raise HTTPException(404, "knowledge base not found")
    return await cleanup.delete_source_files(kb_id, kb.root_path, [path])



@router.get("/token-usage")
async def get_token_usage(db=Depends(get_db_conn)):
    """Get today's global token usage."""
    from datetime import date
    today = date.today().isoformat()
    async with db.execute("SELECT tokens_used FROM token_usage WHERE date=?", (today,)) as cur:
        row = await cur.fetchone()
        used = row[0] if row else 0
    async with db.execute("SELECT value FROM config WHERE key='token_quota_global'") as cur:
        row = await cur.fetchone()
        quota = int(row[0]) if row else 0
    return {"used": used, "quota": quota, "date": today}


@router.post("/token-quota")
async def set_token_quota(kb_id: str, quota: int = 0, db=Depends(get_db_conn)):
    """Set daily global token quota in millions. 0 = unlimited."""
    tokens = quota * 1_000_000
    await db.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('token_quota_global', ?)", (str(tokens),))
    await db.commit()
    return {"quota_m": quota, "quota_tokens": tokens}


@router.get("/review-items")
async def get_review_items(kb_id: str, db=Depends(get_db_conn)):
    """Get pending merge review items for crystals and communities."""
    # reading from review_queue
    async with db.execute("SELECT value FROM config WHERE key=?", (f"review_queue_{kb_id}",)) as cur:
        row = await cur.fetchone()
        items = json.loads(row[0]) if row else []
    async with db.execute("SELECT value FROM config WHERE key=?", (f"resolved_merges_{kb_id}",)) as cur:
        row = await cur.fetchone()
        resolved = set(json.loads(row[0])) if row else set()
    pending = [i for i in items if i.get("id", "") not in resolved]
    return {"items": pending, "total": len(pending)}


@router.post("/review-items/detect")
async def detect_duplicates(
    kb_id: str,
    registry: KBRegistry = Depends(get_registry),
    db=Depends(get_db_conn),
):
    """Manually trigger duplicate detection on existing crystals and communities."""
    kb = await registry.get(kb_id)
    if kb is None:
        raise HTTPException(404, "knowledge base not found")

    from ..services.merge_detector import MergeDetector
    from ..deps import get_llm

    llm = await get_llm()
    detector = MergeDetector(db, llm=llm)
    result = await detector.detect_and_merge(kb_id, kb.root_path)
    return result


@router.post("/review-items/{item_id}/resolve")
async def resolve_review(
    kb_id: str,
    item_id: str,
    action: str = "keep",
    registry: KBRegistry = Depends(get_registry),
    db=Depends(get_db_conn),
):
    """Resolve a merge review: keep (skip), use_a (delete B), use_b (delete A)."""
    kb = await registry.get(kb_id)
    if kb is None:
        raise HTTPException(404, "knowledge base not found")
    root = Path(kb.root_path)

    async with db.execute("SELECT value FROM config WHERE key=?", (f"review_queue_{kb_id}",)) as cur:
        row = await cur.fetchone()
        items = json.loads(row[0]) if row else []
    async with db.execute("SELECT value FROM config WHERE key=?", (f"resolved_merges_{kb_id}",)) as cur:
        row = await cur.fetchone()
        resolved = set(json.loads(row[0])) if row else set()

    # Find the merge item
    item = next((i for i in items if i.get("id", "") == item_id), None)
    if item is None:
        raise HTTPException(404, "review item not found")

    def _delete_file(rel_path):
        target = root / rel_path
        if target.exists():
            target.unlink()

    if action == "use_a":
        _delete_file(item["item_b"]["path"])
    elif action == "use_b":
        _delete_file(item["item_a"]["path"])
    elif action == "delete_both":
        _delete_file(item["item_a"]["path"])
        _delete_file(item["item_b"]["path"])

    # Mark resolved
    resolved.add(item_id)
    await db.execute(
        "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
        (f"resolved_merges_{kb_id}", json.dumps(list(resolved))),
    )
    await db.commit()

    pending = [i for i in items if i.get("id", "") not in resolved]
    return {"items": pending, "total": len(pending), "resolved": item_id, "action": action}


# ── Document queue ──

@router.get("/documents")
async def list_documents(
    kb_id: str,
    status: str = "",
    registry: KBRegistry = Depends(get_registry),
    sr: SourceRegistry = Depends(get_source_registry),
):
    """List documents with optional status filter. status=active returns queue + processing."""
    kb = await registry.get(kb_id)
    if kb is None:
        raise HTTPException(404, "knowledge base not found")
    if status == "active":
        return await sr.get_active(kb_id)
    return await sr.list_by_kb(kb_id, status)


@router.post("/documents/cancel")
async def cancel_document(
    kb_id: str,
    path: str,
    registry: KBRegistry = Depends(get_registry),
    sr: SourceRegistry = Depends(get_source_registry),
):
    """Cancel a queued document (raw/indexed only)."""
    kb = await registry.get(kb_id)
    if kb is None:
        raise HTTPException(404, "knowledge base not found")
    ok = await sr.cancel(kb_id, path)
    if not ok:
        raise HTTPException(400, "can only cancel queued (raw/indexed) documents")
    return {"status": "cancelled"}


@router.post("/documents/retry")
async def retry_document(
    kb_id: str,
    path: str,
    registry: KBRegistry = Depends(get_registry),
    sr: SourceRegistry = Depends(get_source_registry),
):
    """Retry a failed or cancelled document."""
    kb = await registry.get(kb_id)
    if kb is None:
        raise HTTPException(404, "knowledge base not found")
    ok = await sr.retry(kb_id, path)
    if not ok:
        raise HTTPException(400, "can only retry failed/cancelled documents")
    return {"status": "raw"}


@router.delete("/documents")
async def delete_document(
    kb_id: str,
    path: str,
    registry: KBRegistry = Depends(get_registry),
    sr: SourceRegistry = Depends(get_source_registry),
):
    """Delete a document from queue and source registry. Does NOT delete the physical file."""
    kb = await registry.get(kb_id)
    if kb is None:
        raise HTTPException(404, "knowledge base not found")
    await sr.delete(kb_id, path)
    return {"status": "deleted"}


# ── Schedule config ──

@router.get("/schedule")
async def get_schedule(kb_id: str, db=Depends(get_db_conn)):
    async with db.execute("SELECT value FROM config WHERE key=?", (f"schedule_{kb_id}",)) as cur:
        row = await cur.fetchone()
        return json.loads(row[0]) if row else {}


@router.put("/schedule")
async def set_schedule(kb_id: str, config: dict, db=Depends(get_db_conn)):
    await db.execute(
        "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
        (f"schedule_{kb_id}", json.dumps(config)),
    )
    await db.commit()
    return {"status": "saved"}


# ── Job history ──

@router.get("/job-history")
async def get_job_history(
    kb_id: str,
    date: str = "",
    db=Depends(get_db_conn),
):
    """Get job history. If date provided (YYYY-MM-DD), return jobs for that day only."""
    if date:
        async with db.execute(
            "SELECT * FROM jobs WHERE kb_id=? AND date(created_at)=? AND status IN ('done','failed','cancelled') "
            "ORDER BY created_at DESC LIMIT 50",
            (kb_id, date),
        ) as cursor:
            return [dict(row) async for row in cursor]
    from datetime import date as dt
    today = dt.today().isoformat()
    async with db.execute(
        "SELECT * FROM jobs WHERE kb_id=? AND date(created_at)=? "
        "ORDER BY CASE status WHEN 'running' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END, created_at DESC LIMIT 50",
        (kb_id, today),
    ) as cursor:
        return [dict(row) async for row in cursor]


# ── Page links ──

@router.get("/page-links")
async def get_page_links(
    kb_id: str,
    path: str,
    direction: str = "both",
    registry: KBRegistry = Depends(get_registry),
):
    """Get [[wikilinks]] for a page. direction: out, in, or both."""
    import re
    kb = await registry.get(kb_id)
    if kb is None:
        raise HTTPException(404, "knowledge base not found")
    root = Path(kb.root_path)

    full_path = root / path
    if not full_path.exists():
        raise HTTPException(404, "page not found")

    result = {"path": path, "outgoing": [], "incoming": []}

    if direction in ("out", "both"):
        try:
            text = full_path.read_text(encoding="utf-8")
            for m in re.finditer(r"\[\[([^\]|#]+)(?:[|#][^\]]+)?\]\]", text):
                result["outgoing"].append({"target": m.group(1), "text": m.group(0)})
        except Exception:
            pass

    if direction in ("in", "both"):
        wiki_dir = find_wiki_dir(root)
        if wiki_dir.exists():
            search_name = full_path.stem
            for md_file in wiki_dir.rglob("*.md"):
                try:
                    content = md_file.read_text(encoding="utf-8")
                    pattern = rf"\[\[{re.escape(search_name)}(?:[\]|#])"
                    if re.search(pattern, content) or f"[[{path}]]" in content:
                        rel = str(md_file.relative_to(root))
                        if rel != path:
                            result["incoming"].append(rel)
                except Exception:
                    pass

    return result


# ── Page patch ──

@router.post("/page-patch")
async def page_patch(
    kb_id: str,
    body: dict,
    registry: KBRegistry = Depends(get_registry),
):
    path = body.get("path", "")
    section = body.get("section", "")
    action = body.get("action", "append")
    content = body.get("content", "")
    """Incremental edit: append/replace/delete a section in a wiki page."""
    kb = await registry.get(kb_id)
    if kb is None:
        raise HTTPException(404, "knowledge base not found")
    root = Path(kb.root_path)
    full_path = root / path
    if not full_path.exists():
        raise HTTPException(404, "page not found")

    text = full_path.read_text(encoding="utf-8")
    import re

    if action == "append":
        full_path.write_text(text.rstrip() + f"\n\n{content}\n", encoding="utf-8")
    elif action == "prepend":
        full_path.write_text(f"{content}\n\n{text}", encoding="utf-8")
    elif action == "replace" and section:
        pattern = rf"(^#{1,6}\s*{re.escape(section)}.*?)(?=\n#{1,6}\s|\Z)"
        new_text = re.sub(pattern, f"## {section}\n\n{content}\n", text, flags=re.MULTILINE | re.DOTALL)
        if new_text != text:
            full_path.write_text(new_text, encoding="utf-8")
        else:
            full_path.write_text(text.rstrip() + f"\n\n## {section}\n\n{content}\n", encoding="utf-8")
    elif action == "delete" and section:
        pattern = rf"(^#{1,6}\s*{re.escape(section)}.*?)(?=\n#{1,6}\s|\Z)"
        new_text = re.sub(pattern, "", text, flags=re.MULTILINE | re.DOTALL)
        full_path.write_text(new_text, encoding="utf-8")
    else:
        raise HTTPException(400, f"unknown action: {action}")

    return {"status": "patched", "action": action, "path": path}


# ── Semantic search (LLM rerank) ──

@router.post("/search/semantic")
async def semantic_search(
    kb_id: str,
    body: dict,
    db=Depends(get_db_conn),
):
    """LLM rerank: FTS5 candidates → LLM scores → top N results."""
    from ..deps import get_llm
    from ..services.token_tracker import TokenTracker

    query = body.get("query", "")
    candidates = body.get("candidates", [])
    top_n = body.get("top_n", 5)

    if not candidates:
        return {"query": query, "results": [], "hint": "no candidates provided"}

    trimmed = candidates[:20]
    items = "\n".join(
        f"{i+1}. {c.get('title', c.get('path', '?'))}: {c.get('snippet', '')[:200]}"
        for i, c in enumerate(trimmed)
    )
    prompt = f"""Query: {query}

Rank these pages by relevance to the query (score 0-100):
{items}

Return JSON: {{"ranked": [{{"rank": 1, "score": 95, "reason": "one sentence why"}}, ...]}}
Respond ONLY with valid JSON, no markdown fences."""

    try:
        llm = await get_llm()
        tracker = TokenTracker()
        result, tokens = await tracker.chat(llm, [
            {"role": "system", "content": "You rank search results by relevance. Output only valid JSON."},
            {"role": "user", "content": prompt},
        ], max_tokens=500)

        from ..services.llm_utils import clean_json
        ranked = json.loads(clean_json(result)).get("ranked", [])
        ranked.sort(key=lambda x: x.get("score", 0), reverse=True)
        top = ranked[:top_n]

        return {
            "query": query,
            "candidates": len(trimmed),
            "tokens_used": tokens,
            "results": top,
        }
    except Exception as e:
        return {"query": query, "error": str(e), "results": []}