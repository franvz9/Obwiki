"""Community Generator — reads clusters.json and generates communities/*.md hub pages.

Each community hub page is a markdown file with [[wikilinks]] to all member pages.
These hub pages create natural clusters in Obsidian's graph view.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import aiosqlite


class CommunityGenerator:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def generate(self, kb_id: str, root_path: str) -> dict:
        root = Path(root_path)
        clusters_path = root / ".llmwiki" / "graph" / "clusters.json"

        if not clusters_path.exists():
            return {"status": "no clusters found — run Evolve first"}

        clusters = json.loads(clusters_path.read_text())
        if not clusters:
            return {"status": "no clusters found"}

        # Cache: skip if clusters.json unchanged since last run
        import hashlib
        clusters_hash = hashlib.sha256(clusters_path.read_bytes()).hexdigest()[:16]
        cache_path = root / ".llmwiki" / "graph" / ".community_cache"
        if cache_path.exists():
            try:
                if cache_path.read_text().strip() == clusters_hash:
                    return {"status": "cached — clusters unchanged", "created": 0, "updated": 0, "total": 0}
            except Exception:
                pass

        from ..paths import COMMUNITIES_DIR
        communities_dir = root / COMMUNITIES_DIR
        communities_dir.mkdir(parents=True, exist_ok=True)

        created = []
        updated = []
        today = date.today().isoformat()

        def _slug(name: str) -> str:
            return (name or "unnamed").lower().replace(" ", "-").replace("/", "-").replace("'", "").replace(":", "")[:80]

        def _write_community(c: dict, parent_dir: Path, parent_slug: str = ""):
            name = c.get("name", "unnamed")
            pages = c.get("pages", [])
            theme = c.get("theme", "")
            cohesion = c.get("cohesion", 0)
            level = c.get("level", 1)
            children = c.get("children", [])

            slug = _slug(name)
            file_path = parent_dir / f"{slug}.md"

            # Build content
            lines = [
                f"---",
                f"type: community",
                f"name: {name}",
                f"cohesion: {cohesion:.0%}",
                f"members: {len(pages)}",
                f"level: {level}",
            ]
            if parent_slug:
                lines.append(f"parent: {parent_slug}")
            if children:
                child_list = ", ".join(_slug(ch.get("name", "")) for ch in children)
                lines.append(f"children: [{child_list}]")
            lines.append(f"updated: {today}")
            lines.append(f"---")
            lines.append(f"\n# {name}\n")
            if theme:
                lines.append(f"{theme}\n")
            lines.append(f"## Members ({len(pages)})\n")
            for p in pages:
                wiki_path = p.replace("wiki/", "")
                lines.append(f"- [[{wiki_path}]]")
            if children:
                lines.append(f"\n## Sub-communities\n")
                for ch in children:
                    ch_slug = _slug(ch.get("name", ""))
                    lines.append(f"- [[{slug}/{ch_slug}|{ch.get('name', 'Sub')}]]")

            full = "\n".join(lines)
            existed = file_path.exists()
            file_path.write_text(full, encoding="utf-8")

            if existed:
                updated.append(str(file_path.relative_to(root)))
            else:
                created.append(str(file_path.relative_to(root)))

            # Recursively write children in subdirectory
            if children:
                child_dir = parent_dir / slug
                child_dir.mkdir(parents=True, exist_ok=True)
                for ch in children:
                    _write_community(ch, child_dir, slug)

        # Flatten and write all communities
        def _flatten_write(clist: list[dict], parent_dir: Path):
            for c in clist:
                if len(c.get("pages", [])) >= 3:  # >=3 nodes for community
                    _write_community(c, parent_dir)

        _flatten_write(clusters, communities_dir)

        # Clean orphans: all valid slugs across hierarchy
        valid_slugs = set()
        def _collect_slugs(clist: list[dict]):
            for c in clist:
                if len(c.get("pages", [])) >= 3:
                    valid_slugs.add(_slug(c.get("name", "")))
                    if c.get("children"):
                        _collect_slugs(c["children"])
        _collect_slugs(clusters)

        for md_file in communities_dir.rglob("*.md"):
            if md_file.stem not in valid_slugs:
                try:
                    md_file.unlink()
                except Exception:
                    pass

        cache_path.write_text(clusters_hash)

        return {
            "created": len(created),
            "updated": len(updated),
            "total": len(created) + len(updated),
            "levels": max((c.get("level", 1) for c in clusters), default=1),
        }
