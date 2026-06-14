from __future__ import annotations
from ..paths import INBOX_DIR, META_DIR, WIKI_DIR, COMMUNITIES_DIR, LLMWIKI_DIR, OPS_DIR, INDEX_FILE, OVERVIEW_FILE, LOG_FILE, SCHEMA_FILE, CACHE_DIR

import json
from pathlib import Path

import aiosqlite
import yaml

from .llm import LLMClient
from .llm_utils import clean_json
from .token_tracker import TokenTracker


CRYSTALLIZE_PROMPT = """You are a knowledge synthesizer. Your job is to read multiple related wiki pages and produce a "crystal" — a high-quality, consolidated knowledge unit that captures the essential understanding.

Related wiki pages:
---
{wiki_pages}
---

Wiki overview:
{wiki_overview}

Produce a JSON crystal:

{{
  "title": "Crystal title — concise and descriptive",
  "summary": "One-paragraph summary capturing the essential insight",
  "key_findings": ["finding 1", "finding 2", ...],
  "evidence_chain": [
    {{"from": "source-page.md", "claim": "what it says", "strength": "strong|moderate|weak"}}
  ],
  "confidence": 0.0-1.0,
  "open_questions": ["question 1", ...],
  "related_crystals": ["title of related crystal concept"],
  "content": "Full markdown body with [[wikilinks]], synthesizing the knowledge across sources"
}}

Rules:
1. Crystals should be context-independent — a reader should understand them without seeing the sources
2. Prefer high-confidence claims backed by multiple sources
3. Flag contradictions across sources honestly
4. Use [[wikilinks]] to reference wiki pages
5. Keep the content clear and well-structured

**Language**: Keep the original language of source wiki pages. Do NOT auto-translate.

**Dedup**: Use [[wikilink]] to reference existing wiki pages for entities/concepts, even if they exist in another language. Do not create synonyms.

Respond ONLY with valid JSON, no markdown fences."""


class Crystallizer:
    def __init__(self, db: aiosqlite.Connection, llm: LLMClient):
        self.db = db
        self.llm = llm

    async def crystallize(self, kb_id: str, root_path: str, topic: str = "") -> dict:
        root = Path(root_path)
        from .wiki_schema import find_wiki_dir; wiki_dir = find_wiki_dir(root)

        if not wiki_dir.exists():
            return {"status": "no wiki directory"}

        # Read clusters from evolve output
        clusters_path = root / LLMWIKI_DIR / "graph" / "clusters.json"
        if not clusters_path.exists():
            return {"status": "no clusters found — run Evolve first"}

        clusters_raw = json.loads(clusters_path.read_text())
        if not clusters_raw:
            return {"status": "no clusters found"}

        # Cache: skip if clusters.json unchanged and crystals already exist
        import hashlib
        clusters_hash = hashlib.sha256(clusters_path.read_bytes()).hexdigest()[:16]
        cache_path = root / LLMWIKI_DIR / "graph" / ".crystal_cache"
        crystals_dir = wiki_dir / "crystals"
        if cache_path.exists() and crystals_dir.exists() and any(crystals_dir.iterdir()):
            try:
                if cache_path.read_text().strip() == clusters_hash:
                    count = len(list(crystals_dir.rglob("*.md")))
                    return {"status": "cached — clusters unchanged", "crystals_created": 0, "total_clusters": count, "cluster_skipped": 0, "tokens": 0}
            except Exception:
                pass

        # Flatten hierarchical clusters
        def _flatten(clist: list[dict]) -> list[dict]:
            result = []
            for c in clist:
                result.append(c)
                if c.get("children"):
                    result.extend(_flatten(c["children"]))
            return result
        clusters = _flatten(clusters_raw)

        # Filter by topic if specified
        if topic:
            clusters = [c for c in clusters if topic.lower() in c.get("name", "").lower()
                        or topic.lower() in c.get("theme", "").lower()]

        # Filter: min pages + min cohesion
        clusters = [c for c in clusters if len(c.get("pages", [])) >= 5 and c.get("cohesion", 0) >= 0.75]
        if not clusters:
            return {"status": "no eligible clusters after filtering (need >=5 pages, >=75% cohesion)"}

        # Dedup: skip clusters whose theme is too similar to a higher-cohesion cluster
        import re as _re
        def _tokenize(s: str) -> set:
            return set(_re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', s.lower()))
        clusters.sort(key=lambda c: c.get("cohesion", 0), reverse=True)
        deduped = []
        for c in clusters:
            ct = _tokenize(c.get("theme", ""))
            too_close = False
            for kept in deduped:
                kt = _tokenize(kept.get("theme", ""))
                if ct and kt and len(ct & kt) / min(len(ct), len(kt)) > 0.6:
                    too_close = True
                    break
            if not too_close:
                deduped.append(c)

        if not deduped:
            return {"status": "no eligible clusters after filtering + dedup"}

        # Pre-load all wiki pages into a lookup
        pages_map = {}
        for md_file in wiki_dir.rglob("*.md"):
            try:
                rel = str(md_file.relative_to(root))
                pages_map[rel] = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

        # Read overview for context
        overview = ""
        overview_path = root / META_DIR / OVERVIEW_FILE
        if overview_path.exists():
            overview = overview_path.read_text(encoding="utf-8")[:2000]

        tracker = TokenTracker()
        crystals_dir = wiki_dir / "crystals"
        crystals_dir.mkdir(exist_ok=True)
        created = []
        skipped = 0

        for cluster in deduped:
            name = cluster.get("name", "unnamed")
            cohesion = cluster.get("cohesion", 0)
            member_paths = cluster.get("pages", [])
            # Filter: require min pages and min cohesion
            if len(member_paths) < 5 or cohesion < 0.75:
                skipped += 1
                continue

            # Collect content for this cluster's pages
            pages_in = {}
            for p in member_paths:
                if p in pages_map:
                    pages_in[p] = pages_map[p]

            if len(pages_in) < 2:
                skipped += 1
                continue

            pages_text = "\n\n---\n\n".join(
                f"### {p}\n{content[:2000]}" for p, content in list(pages_in.items())[:10]
            )

            result, _ = await tracker.chat(self.llm, [
                {"role": "system", "content": "You are a knowledge synthesizer. Output only valid JSON."},
                {"role": "user", "content": CRYSTALLIZE_PROMPT.format(
                    wiki_pages=pages_text,
                    wiki_overview=overview,
                )},
            ])

            try:
                data = json.loads(clean_json(result))
            except json.JSONDecodeError:
                continue

            slug = data.get("title", name).lower().replace(" ", "-").replace("/", "-").replace(":", "-")[:80]
            crystal_path = crystals_dir / f"{slug}.md"

            fm = {
                "type": "crystal",
                "title": data.get("title", name),
                "sources": list(pages_in.keys()),
                "confidence": data.get("confidence", 0.5),
                "cluster": name,
            }
            fm_str = yaml.dump(fm, allow_unicode=True, default_flow_style=False).strip()
            body = data.get("content", data.get("summary", ""))
            crystal_path.write_text(f"---\n{fm_str}\n---\n\n{body}", encoding="utf-8")

            created.append({
                "path": str(crystal_path.relative_to(root)),
                "title": data.get("title"),
                "confidence": data.get("confidence"),
                "sources": len(pages_in),
            })

        # Write-back to overview
        ov_path = root / META_DIR / OVERVIEW_FILE
        for c in created:
            backlink = f"\n\n## Crystal: {c['title']}\nConfidence: {c['confidence']:.0%}, from {c['sources']} pages. See {c['path']}\n"
            if ov_path.exists():
                ov_path.write_text(ov_path.read_text(encoding="utf-8") + backlink, encoding="utf-8")

        cache_path.write_text(clusters_hash)

        return {
            "crystals_created": len(created),
            "clusters_skipped": skipped,
            "clusters_deduped": len(deduped) - len(created),
            "total_clusters": len(deduped),
            "tokens": tracker.total,
        }


