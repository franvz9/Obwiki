from __future__ import annotations
from ..paths import INBOX_DIR, META_DIR, WIKI_DIR, COMMUNITIES_DIR, LLMWIKI_DIR, OPS_DIR, INDEX_FILE, OVERVIEW_FILE, LOG_FILE, SCHEMA_FILE, CACHE_DIR

import json
import re
from collections import defaultdict
from pathlib import Path

import aiosqlite
import yaml

from .llm import LLMClient
from .llm_utils import clean_json
from .token_tracker import TokenTracker


EVOLVE_PROMPT = """You are a knowledge graph analyst. Given a set of wiki pages, discover relationships, clusters, and themes.

Wiki pages:
---
{wiki_pages}
---

Wiki index:
{wiki_index}

Produce a JSON analysis:

{{
  "relationships": [
    {{
      "source": "page-path.md",
      "target": "page-path.md",
      "type": "supports|contradicts|extends|generalizes|example_of|depends_on|related",
      "reason": "one sentence explaining why"
    }}
  ],
  "clusters": [
    {{
      "name": "cluster name",
      "theme": "one paragraph describing the theme",
      "pages": ["page-path.md", ...],
      "cohesion": 0.0-1.0
    }}
  ],
  "bridge_pages": [
    {{
      "page": "page-path.md",
      "connects_clusters": ["cluster1", "cluster2"],
      "reason": "why this page bridges these clusters"
    }}
  ],
  "gaps": [
    {{
      "description": "knowledge gap description",
      "suggested_query": "search query to fill this gap"
    }}
  ],
  "overview_update": "updated overview paragraph for overview.md"
}}

**Language**: Use the wiki's dominant language(s). Do NOT auto-translate page names.

**Dedup**: Do NOT create separate nodes for Chinese-English variants of the same concept — link them to the existing page.

Focus on discovering non-obvious connections, identifying knowledge clusters, and flagging gaps.
Respond ONLY with valid JSON, no markdown fences."""


class Evolver:
    def __init__(self, db: aiosqlite.Connection, llm: LLMClient):
        self.db = db
        self.llm = llm

    async def evolve(self, kb_id: str, root_path: str, scope: str = "all") -> dict:
        root = Path(root_path)
        from .wiki_schema import find_wiki_dir; wiki_dir = find_wiki_dir(root)

        if not wiki_dir.exists():
            return {"status": "no wiki directory"}

        # Collect wiki pages (exclude crystals — they are outputs, not inputs)
        pages = []
        for md_file in wiki_dir.rglob("*.md"):
            if "crystals" in str(md_file.relative_to(wiki_dir)).replace("\\", "/").split("/"):
                continue
            try:
                text = md_file.read_text(encoding="utf-8")
                pages.append({
                    "path": str(md_file.relative_to(root)),
                    "content": text[:1500],
                    "frontmatter": _parse_frontmatter(text),
                })
            except Exception:
                continue

        if len(pages) < 2:
            return {"status": "not enough pages for evolution (need >= 2)"}

        wiki_index = ""
        index_path = root / META_DIR / INDEX_FILE
        if index_path.exists():
            wiki_index = index_path.read_text(encoding="utf-8")[:3000]

        # Cache check: skip LLM if wiki hasn't changed since last evolve
        import hashlib
        pages_fingerprint = hashlib.sha256(
            "|".join(f"{p['path']}:{len(p['content'])}" for p in sorted(pages, key=lambda x: x['path'])).encode()
        ).hexdigest()[:16]

        cache_path = root / LLMWIKI_DIR / "graph" / ".evolve_cache"
        edges_path = root / LLMWIKI_DIR / "graph" / "edges.json"
        clusters_path = root / LLMWIKI_DIR / "graph" / "clusters.json"
        gaps_path = root / LLMWIKI_DIR / "graph" / "gaps.json"

        cached_hash = ""
        if cache_path.exists():
            try:
                cached_hash = cache_path.read_text().strip()
            except Exception:
                pass

        if cached_hash == pages_fingerprint and edges_path.exists() and clusters_path.exists():
            existing_edges = json.loads(edges_path.read_text())
            existing_clusters = json.loads(clusters_path.read_text())
            existing_gaps = json.loads(gaps_path.read_text()) if gaps_path.exists() else []
            return {
                "status": "cached — wiki unchanged",
                "relationships_found": len(existing_edges),
                "clusters_found": len(existing_clusters),
                "gaps_found": len(existing_gaps),
                "total_pages_analyzed": len(pages),
                "tokens": 0,
            }

        graph_dir = root / LLMWIKI_DIR / "graph"
        graph_dir.mkdir(parents=True, exist_ok=True)

        # Batch pages: LLM discovers relationships (edges)
        batch_size = 20
        all_relationships = []
        all_bridges = []
        all_gaps = []

        tracker = TokenTracker()
        for i in range(0, len(pages), batch_size):
            batch = pages[i:i + batch_size]
            pages_text = "\n\n".join(
                f"### {p['path']}\n{p['content']}" for p in batch
            )

            result, _ = await tracker.chat(self.llm, [
                {"role": "system", "content": "You are a knowledge graph analyst. Output only valid JSON."},
                {"role": "user", "content": EVOLVE_PROMPT.format(
                    wiki_pages=pages_text,
                    wiki_index=wiki_index,
                )},
            ])

            try:
                data = json.loads(clean_json(result))
                all_relationships.extend(data.get("relationships", []))
                all_bridges.extend(data.get("bridge_pages", []))
                all_gaps.extend(data.get("gaps", []))
            except json.JSONDecodeError:
                continue

        # Build graph + Louvain community detection
        graph_dir = root / LLMWIKI_DIR / "graph"
        graph_dir.mkdir(parents=True, exist_ok=True)
        communities = self._louvain_cluster(all_relationships, pages)

        # LLM names each community (batch all into one prompt)
        named_communities, naming_tokens = await self._name_communities(communities, wiki_index)

        # Save edges
        edges_path = graph_dir / "edges.json"
        existing_edges = []
        if edges_path.exists():
            try:
                existing_edges = json.loads(edges_path.read_text())
            except Exception:
                pass
        new_edges = [
            {"source": r["source"], "target": r["target"],
             "type": r.get("type", "related"), "reason": r.get("reason", "")}
            for r in all_relationships
        ]
        existing_edges.extend(new_edges)
        edges_path.write_text(json.dumps(existing_edges, ensure_ascii=False, indent=2))

        # Save clusters
        clusters_path = graph_dir / "clusters.json"
        clusters_path.write_text(json.dumps(named_communities, ensure_ascii=False, indent=2))

        # Save gaps
        gaps_path = graph_dir / "gaps.json"
        gaps_path.write_text(json.dumps(all_gaps, ensure_ascii=False, indent=2))

        # Save cache fingerprint
        cache_path.write_text(pages_fingerprint)

        # Update overview
        overview_update = ""
        for c in named_communities:
            overview_update += f"\n## {c['name']}\n{c.get('theme', '')}\n"
        overview_path = root / META_DIR / OVERVIEW_FILE
        if overview_path.exists():
            current = overview_path.read_text(encoding="utf-8")
            overview_path.write_text(current + "\n" + overview_update, encoding="utf-8")
        else:
            overview_path.write_text(f"# Overview\n\n{overview_update}", encoding="utf-8")

        return {
            "relationships_found": len(all_relationships),
            "bridges_found": len(all_bridges),
            "gaps_found": len(all_gaps),
            "clusters_found": len(named_communities),
            "total_pages_analyzed": len(pages),
            "tokens": tracker.total + naming_tokens,
        }

    def _louvain_cluster(self, relationships: list[dict], pages: list[dict]) -> list[dict]:
        """Build graph from edges, run hierarchical Louvain with soft assignment."""
        import networkx as nx
        from networkx.algorithms import community as nx_community
        from community import community_louvain  # python-louvain

        edge_weights = {
            "supports": 2, "extends": 2, "generalizes": 2,
            "depends_on": 1.5, "example_of": 1.5, "related": 1, "contradicts": 0.5,
        }

        G = nx.Graph()
        for r in relationships:
            src, tgt, rtype = r["source"], r["target"], r.get("type", "related")
            w = edge_weights.get(rtype, 1)
            if G.has_edge(src, tgt):
                G[src][tgt]["weight"] += w
            else:
                G.add_edge(src, tgt, weight=w)

        if G.number_of_nodes() < 3:
            return []

        # Soft assignment helpers
        def _soft_assign(G, members):
            extended = set(members)
            for node in list(G.nodes):
                if node in extended:
                    continue
                comm_edges = sum(
                    G[node][nb].get("weight", 1)
                    for nb in G.neighbors(node) if nb in members
                )
                total = sum(G[node][nb].get("weight", 1) for nb in G.neighbors(node))
                if total > 0 and comm_edges / total > 0.2:
                    extended.add(node)
            return sorted(extended)

        def _cohesion(G, members):
            internal = sum(1 for u in members for v in G.neighbors(u) if v in members)
            boundary = sum(1 for u in members for v in G.neighbors(u) if v not in members)
            return round(internal / (internal + boundary + 1), 2)

        def _build_cluster(G, members, level=1) -> dict:
            pages = _soft_assign(G, members)
            return {
                "name": "",
                "theme": "",
                "pages": pages,
                "cohesion": _cohesion(G, members),
                "level": level,
                "children": [],
            }

        def _subdivide(G, members, level=1, max_level=3):
            """Recursively subdivide communities."""
            if len(members) < 6 or level >= max_level:
                return []
            sub = G.subgraph(members).copy()
            if sub.number_of_edges() < 2:
                return []

            try:
                partition = community_louvain.best_partition(sub, weight="weight", random_state=42)
            except Exception:
                return []

            # Group nodes by partition
            groups = {}
            for node, gid in partition.items():
                groups.setdefault(gid, []).append(node)

            if len(groups) <= 1:
                return []

            children = []
            for g_members in groups.values():
                if len(g_members) >= 3:
                    child = _build_cluster(G, g_members, level + 1)
                    grand = _subdivide(G, g_members, level + 1, max_level)
                    if grand:
                        child["children"] = grand
                    children.append(child)

            return children

        # Level 1: top-level Louvain
        raw = nx_community.louvain_communities(G, weight="weight", seed=42)
        communities = []
        for members in raw:
            if len(members) < 3:
                continue
            c = _build_cluster(G, members, 1)
            c["children"] = _subdivide(G, members, 1)
            communities.append(c)

        return sorted(communities, key=lambda c: len(c["pages"]), reverse=True)

    async def _name_communities(self, communities: list[dict], wiki_index: str) -> tuple[list[dict], int]:
        """Use LLM to generate names and themes for all communities (flatten hierarchy)."""
        if not communities or not self.llm:
            return communities, 0

        # Flatten all communities (all levels) for naming
        def _flatten(clist: list[dict], prefix: str = "") -> list[dict]:
            result = []
            for i, c in enumerate(clist):
                cid = f"{prefix}{i + 1}"
                result.append({"id": cid, "cluster": c, "pages": c["pages"], "cohesion": c["cohesion"]})
                if c.get("children"):
                    result.extend(_flatten(c["children"], f"{cid}."))
            return result

        flat = _flatten(communities)
        if not flat:
            return communities, 0

        summary = ""
        for item in flat:
            pages_sample = item["pages"][:6]
            summary += f"\nCommunity {item['id']} ({len(item['pages'])} pages, cohesion {item['cohesion']}):\n"
            for p in pages_sample:
                summary += f"  - {p}\n"

        prompt = f"""Name these knowledge communities based on their member pages.

Wiki index for context:
{wiki_index[:2000]}

{summary}

For each community, produce a concise name (5-8 words) and a one-paragraph theme description.
Output as JSON array:
[
  {{"community": "1", "name": "...", "theme": "..."}},
  ...
]

Respond ONLY with valid JSON array, no markdown fences."""

        try:
            naming_tracker = TokenTracker()
            result, _ = await naming_tracker.chat(self.llm, [
                {"role": "system", "content": "You name knowledge communities. Output only a JSON array."},
                {"role": "user", "content": prompt},
            ])
            tokens = naming_tracker.total
            names = json.loads(clean_json(result))
            if isinstance(names, list):
                # Map names back to hierarchy
                name_map = {item["community"]: item for item in names}
                for item in flat:
                    cid = item["id"]
                    if cid in name_map:
                        item["cluster"]["name"] = name_map[cid].get("name", "")
                        item["cluster"]["theme"] = name_map[cid].get("theme", "")
        except Exception:
            pass

        return communities, tokens


def _parse_frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    try:
        end = text.index("---", 3)
        return yaml.safe_load(text[3:end]) or {}
    except Exception:
        return {}


