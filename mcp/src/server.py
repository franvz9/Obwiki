#!/usr/bin/env python3
"""LLMWiki MCP Server — AI agent tool surface for knowledge base operations.

Usage:
  uv run mcp run src/server.py      # Production (stdio)
  uv run mcp dev src/server.py      # Development

Config:
  LLMWIKI_API_URL  — API base URL (default: http://localhost:8742)
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP

API_URL = os.getenv("LLMWIKI_API_URL", "http://localhost:8742").rstrip("/")

mcp = FastMCP("obwiki-mcp")


async def _get(path: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{API_URL}{path}")
        r.raise_for_status()
        return r.json()


async def _post(path: str, data: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{API_URL}{path}", json=data or {})
        r.raise_for_status()
        return r.json()


async def _put(path: str, data: dict) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.put(f"{API_URL}{path}", json=data)
        r.raise_for_status()
        return r.json()


async def _resolve_kb(kb_id: str | None) -> str:
    if kb_id:
        return kb_id
    kb = await _get("/v1/kbs/active")
    return kb["id"]


# ── Knowledge Base Management ──

@mcp.tool()
async def kb_list() -> str:
    """列出所有已注册的知识库"""
    return json.dumps(await _get("/v1/kbs"), ensure_ascii=False, indent=2)


@mcp.tool()
async def kb_status(kb_id: str | None = None) -> str:
    """获取知识库详细状态"""
    kid = await _resolve_kb(kb_id)
    return json.dumps(await _get(f"/v1/kbs/{kid}"), ensure_ascii=False, indent=2)


@mcp.tool()
async def kb_activate(kb_id: str) -> str:
    """激活指定知识库为当前工作库"""
    return json.dumps(await _post(f"/v1/kbs/{kb_id}/activate"), ensure_ascii=False, indent=2)


@mcp.tool()
async def kb_overview(kb_id: str | None = None) -> str:
    """返回知识库全局概要：统计 + 最新变化"""
    kid = await _resolve_kb(kb_id)
    dash = await _get(f"/v1/kbs/{kid}/dashboard")
    crystals = await _get(f"/v1/kbs/{kid}/crystals")
    jobs = await _get(f"/v1/kbs/{kid}/jobs?limit=5")
    result = {
        "name": dash.get("name", "unknown"),
        "stats": {
            "sources": dash.get("source", {}),
            "wiki_pages": dash.get("wiki", {}).get("total", 0),
            "crystals": len(crystals) if isinstance(crystals, list) else dash.get("crystals", {}).get("total", 0),
            "graph_edges": dash.get("graph", {}).get("edges", 0),
            "graph_clusters": dash.get("graph", {}).get("clusters", 0),
        },
        "recent_jobs": [{"type": j.get("type"), "status": j.get("status")} for j in (jobs if isinstance(jobs, list) else [])],
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


# ── Search & Read ──

@mcp.tool()
async def kb_search(query: str, kb_id: str | None = None, limit: int = 20, offset: int = 0) -> str:
    """FTS5 全文搜索知识库内容"""
    kid = await _resolve_kb(kb_id)
    return json.dumps(await _post(f"/v1/kbs/{kid}/search", {
        "query": query, "limit": limit, "offset": offset,
    }), ensure_ascii=False, indent=2)


@mcp.tool()
async def kb_semantic_search(query: str, kb_id: str | None = None, top_n: int = 5) -> str:
    """自然语言语义搜索（LLM 重排）"""
    kid = await _resolve_kb(kb_id)
    broad = await _post(f"/v1/kbs/{kid}/search", {"query": query, "limit": 20})
    results = broad.get("results", [])
    if not results:
        return json.dumps({"query": query, "results": [], "hint": "no matches"}, ensure_ascii=False)
    candidates = [{"path": r["path"], "title": r.get("title", ""), "snippet": r.get("snippet", "")} for r in results]
    return json.dumps(await _post(f"/v1/kbs/{kid}/search/semantic", {
        "query": query, "candidates": candidates, "top_n": top_n,
    }), ensure_ascii=False, indent=2)


@mcp.tool()
async def kb_read(path: str, kb_id: str | None = None, include_raw: bool = False) -> str:
    """读取知识库中文件内容。source 页默认跳过 '## 原始文本' 段（摘要约 1-2K），传 include_raw=true 取全文。"""
    kid = await _resolve_kb(kb_id)
    data = await _get(f"/v1/files/{kid}/{path}")
    # Default: skip raw text section for source pages
    if not include_raw and "wiki/sources/" in path:
        if isinstance(data, dict) and "content" in data:
            text = data["content"]
            idx = text.find("\n## 原始文本\n")
            if idx > 0:
                data = {**data, "content": text[:idx] + "\n\n*（原始文本已省略，传 include_raw=true 获取全文）*"}
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool()
async def kb_page_links(path: str, kb_id: str | None = None, direction: str = "both") -> str:
    """获取页面的 [[wikilinks]] 引用和被引用列表"""
    kid = await _resolve_kb(kb_id)
    return json.dumps(await _get(f"/v1/kbs/{kid}/page-links?path={path}&direction={direction}"), ensure_ascii=False, indent=2)


@mcp.tool()
async def kb_browse(path: str, kb_id: str | None = None) -> str:
    """读一页并返回所有 [[wikilinks]] 目标页的摘要"""
    kid = await _resolve_kb(kb_id)
    content = await _get(f"/v1/files/{kid}/{path}")
    text = content if isinstance(content, str) else content.get("content", "")
    links = re.findall(r"\[\[([^\]|#]+)(?:[|#][^\]]+)?\]\]", text)
    summaries = []
    for link in links[:10]:
        try:
            t = await _get(f"/v1/files/{kid}/{link}")
            txt = t if isinstance(t, str) else t.get("content", "")
            summaries.append({"page": link, "preview": txt[:200]})
        except Exception:
            summaries.append({"page": link, "preview": "unavailable"})
    return json.dumps({"page": path, "links": links, "summaries": summaries}, ensure_ascii=False, indent=2)


# ── Ingest (only write path — backend auto-processes) ──

@mcp.tool()
async def kb_ingest(name: str, content: str, kb_id: str | None = None) -> str:
    """存入原始文本到知识库 _inbox/ 目录，作为 .md 源文件。

    文件写入 _inbox/ 后，后台自动化管线会依次执行 scan→organize→extract，
    将内容转换为结构化的 wiki 页面。AI 代理无需手动触发后续处理。

    参数:
      name: 文件名（不含路径，如 "article-2026.md"）
      content: 完整的 Markdown 文本内容"""
    kid = await _resolve_kb(kb_id)
    return json.dumps(await _post(f"/v1/kbs/{kid}/import/file-content", {
        "name": name, "content": content, "encoding": "text",
    }), ensure_ascii=False, indent=2)


@mcp.tool()
async def kb_import(kb_id: str, source_path: str) -> str:
    """导入本地目录到知识库 _inbox/（仅限已有本地文件路径的场景）"""
    return json.dumps(await _post(f"/v1/kbs/{kb_id}/import/folder-json", {
        "source_path": source_path,
    }), ensure_ascii=False, indent=2)


# ── Browse & Index ──

@mcp.tool()
async def kb_tree(kb_id: str | None = None) -> str:
    """获取知识库完整目录树"""
    kid = await _resolve_kb(kb_id)
    return json.dumps(await _get(f"/v1/kbs/{kid}/tree"), ensure_ascii=False, indent=2)


@mcp.tool()
async def kb_graph(kb_id: str | None = None) -> str:
    """获取知识图谱数据：关系边、聚类、知识缺口"""
    kid = await _resolve_kb(kb_id)
    return json.dumps(await _get(f"/v1/kbs/{kid}/graph"), ensure_ascii=False, indent=2)


@mcp.tool()
async def kb_crystals(kb_id: str | None = None) -> str:
    """列出已生成的结晶笔记"""
    kid = await _resolve_kb(kb_id)
    return json.dumps(await _get(f"/v1/kbs/{kid}/crystals"), ensure_ascii=False, indent=2)


@mcp.tool()
async def kb_communities(kb_id: str | None = None) -> str:
    """列出知识聚类/主题社区"""
    kid = await _resolve_kb(kb_id)
    graph = await _get(f"/v1/kbs/{kid}/graph")
    return json.dumps({"clusters": graph.get("clusters", [])}, ensure_ascii=False, indent=2)


# ── Jobs (read-only status) ──

@mcp.tool()
async def kb_jobs(kb_id: str | None = None, job_id: str = "", limit: int = 50) -> str:
    """查看任务状态或任务列表（只读，不触发新任务）"""
    if job_id:
        return json.dumps(await _get(f"/v1/jobs/{job_id}"), ensure_ascii=False, indent=2)
    kid = await _resolve_kb(kb_id)
    return json.dumps(await _get(f"/v1/kbs/{kid}/jobs?limit={limit}"), ensure_ascii=False, indent=2)


# ── Pipeline triggers (ad-hoc, safe — go through proper pipeline) ──

@mcp.tool()
async def kb_evolve(kb_id: str) -> str:
    """触发知识演进：关系发现 + 层次聚类。通常在文档积累较多后手动触发。"""
    return json.dumps(await _post(f"/v1/kbs/{kb_id}/jobs/evolve"), ensure_ascii=False, indent=2)


@mcp.tool()
async def kb_crystallize(kb_id: str) -> str:
    """触发结晶生成：从 wiki 页面合成高置信度结晶。依赖 evolve 产生的 clusters.json。"""
    return json.dumps(await _post(f"/v1/kbs/{kb_id}/jobs/crystallize"), ensure_ascii=False, indent=2)


@mcp.tool()
async def kb_communities_run(kb_id: str) -> str:
    """触发社区检测：从 clusters.json 生成社区 hub 页面。依赖 evolve 先运行。"""
    return json.dumps(await _post(f"/v1/kbs/{kb_id}/jobs/communities"), ensure_ascii=False, indent=2)


@mcp.tool()
async def kb_lint(kb_id: str) -> str:
    """触发健康检查：矛盾检测、孤立页面、质量评分。随时可运行。"""
    return json.dumps(await _post(f"/v1/kbs/{kb_id}/jobs/lint"), ensure_ascii=False, indent=2)


# ── Queue & Config ──

@mcp.tool()
async def kb_documents(kb_id: str | None = None, status: str = "") -> str:
    """查看文档处理队列（只读，队列由后台自动化管理）"""
    kid = await _resolve_kb(kb_id)
    qs = f"?status={status}" if status else ""
    return json.dumps(await _get(f"/v1/kbs/{kid}/documents{qs}"), ensure_ascii=False, indent=2)


@mcp.tool()
async def kb_review_items(kb_id: str | None = None) -> str:
    """查看待审核的重复检测项（只读，合并操作请在 Obsidian 插件中完成）"""
    kid = await _resolve_kb(kb_id)
    return json.dumps(await _get(f"/v1/kbs/{kid}/review-items"), ensure_ascii=False, indent=2)


@mcp.tool()
async def kb_token_usage(kb_id: str = "") -> str:
    """查看今日 token 用量和配额"""
    kid = await _resolve_kb(kb_id if kb_id else None) if kb_id else await _resolve_kb(None)
    return json.dumps(await _get(f"/v1/kbs/{kid}/token-usage"), ensure_ascii=False, indent=2)


@mcp.tool()
async def kb_schedule(kb_id: str | None = None, config: dict | None = None) -> str:
    """查看/设置定时任务配置"""
    kid = await _resolve_kb(kb_id)
    if config:
        return json.dumps(await _put(f"/v1/kbs/{kid}/schedule", config), ensure_ascii=False, indent=2)
    return json.dumps(await _get(f"/v1/kbs/{kid}/schedule"), ensure_ascii=False, indent=2)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
