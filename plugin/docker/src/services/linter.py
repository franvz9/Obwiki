from __future__ import annotations
from ..paths import INBOX_DIR, META_DIR, WIKI_DIR, COMMUNITIES_DIR, LLMWIKI_DIR, OPS_DIR, INDEX_FILE, OVERVIEW_FILE, LOG_FILE, SCHEMA_FILE, CACHE_DIR

import json
from pathlib import Path

import aiosqlite
import yaml

from .llm import LLMClient
from .llm_utils import clean_json


LINT_PROMPT = """You are a wiki quality auditor. Check the following wiki pages for health issues.

Wiki index:
{wiki_index}

Sample wiki pages (not all, a representative subset):
{sample_pages}

Check for:
1. **Contradictions** — pages that make conflicting claims
2. **Stale claims** — information that might be outdated
3. **Orphan pages** — pages with no incoming [[wikilinks]] from other pages
4. **Missing pages** — important concepts/entities mentioned but lacking their own page
5. **Broken wikilinks** — [[wikilinks]] pointing to non-existent pages
6. **Missing frontmatter** — pages without proper YAML frontmatter
7. **Low-quality pages** — pages that are too short, too vague, or missing key sections

Produce JSON:

{{
  "health_score": 0-100,
  "contradictions": [
    {{"page_a": "path.md", "page_b": "path.md", "claim_a": "...", "claim_b": "...", "resolution": "suggested resolution"}}
  ],
  "stale_pages": [
    {{"page": "path.md", "reason": "why it might be stale", "last_updated": "date if known"}}
  ],
  "orphan_pages": ["path1.md", "path2.md"],
  "missing_pages": ["suggested page title 1", ...],
  "broken_links": [{{"page": "path.md", "broken_link": "[[target]]"}}],
  "quality_issues": [
    {{"page": "path.md", "issue": "description", "suggestion": "how to fix"}}
  ],
  "recommended_actions": ["action 1", "action 2"]
}}

**Language**: Do NOT auto-translate page names or suggestions. Keep original language.

Respond ONLY with valid JSON, no markdown fences."""


class Linter:
    def __init__(self, db: aiosqlite.Connection, llm: LLMClient):
        self.db = db
        self.llm = llm

    async def lint(self, kb_id: str, root_path: str, auto_fix: bool = False) -> dict:
        root = Path(root_path)
        from .wiki_schema import find_wiki_dir; wiki_dir = find_wiki_dir(root)

        if not wiki_dir.exists():
            return {"status": "no wiki directory", "health_score": 0}

        wiki_index = ""
        index_path = root / META_DIR / "index.md"
        if index_path.exists():
            wiki_index = index_path.read_text(encoding="utf-8")[:3000]

        # Collect pages
        pages_text = ""
        count = 0
        for md_file in wiki_dir.rglob("*.md"):
            if md_file.name in ("index.md", "overview.md", "log.md"):
                continue
            if count >= 15:
                break
            try:
                text = md_file.read_text(encoding="utf-8")
                pages_text += f"\n### {md_file.relative_to(root)}\n{text[:800]}\n"
                count += 1
            except Exception:
                continue

        if not pages_text:
            return {"status": "no pages to lint", "health_score": 0}

        result, usage = await self.llm.chat_with_usage([
            {"role": "system", "content": "You are a wiki quality auditor. Output only valid JSON."},
            {"role": "user", "content": LINT_PROMPT.format(
                wiki_index=wiki_index,
                sample_pages=pages_text,
            )},
        ])

        try:
            data = json.loads(clean_json(result))
        except json.JSONDecodeError:
            return {"status": "failed to parse LLM output", "health_score": 0}

        # Write lint report
        lint_path = root / OPS_DIR / "lint_report.json"
        lint_path.parent.mkdir(parents=True, exist_ok=True)
        lint_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

        auto_fixed = 0
        if auto_fix:
            auto_fixed = await self._apply_fixes(root, data)

        return {
            "health_score": data.get("health_score", 0),
            "contradictions": len(data.get("contradictions", [])),
            "stale_pages": len(data.get("stale_pages", [])),
            "orphan_pages": len(data.get("orphan_pages", [])),
            "missing_pages": len(data.get("missing_pages", [])),
            "quality_issues": len(data.get("quality_issues", [])),
            "report_path": str(lint_path.relative_to(root)),
            "tokens": usage.get("total_tokens", 0),
            "auto_fixed": auto_fixed,
        }

    async def _apply_fixes(self, root: Path, data: dict) -> int:
        """Auto-fix frontmatter gaps and broken wikilinks. Returns count of fixes applied."""
        from datetime import date
        today = date.today().isoformat()
        fixed = 0

        # Fix broken wikilinks
        for item in data.get("broken_links", []):
            page_path = item.get("page", "")
            broken = item.get("broken_link", "")
            if not page_path or not broken:
                continue
            fp = root / page_path
            if not fp.exists():
                continue
            try:
                text = fp.read_text(encoding="utf-8")
                # Remove [[broken]] and replace with plain text
                link_text = broken.strip("[]")
                new_text = text.replace(broken, link_text)
                if new_text != text:
                    fp.write_text(new_text, encoding="utf-8")
                    fixed += 1
            except Exception:
                continue

        # Fix missing frontmatter
        for page_path in data.get("quality_issues", []):
            # Also check explicit "missing frontmatter" list if we had one
            pass
        # Walk all wiki pages to find those without frontmatter
        from .wiki_schema import find_wiki_dir
        wiki_dir = find_wiki_dir(root)
        if wiki_dir.exists():
            for md_file in wiki_dir.rglob("*.md"):
                if md_file.name in ("index.md", "overview.md", "log.md"):
                    continue
                try:
                    text = md_file.read_text(encoding="utf-8")
                    if not text.startswith("---"):
                        rel = str(md_file.relative_to(root))
                        # Guess type from path
                        ptype = "concept"
                        for t in ["entities", "concepts", "sources", "findings", "comparisons", "synthesis", "queries"]:
                            if t in rel:
                                ptype = t.rstrip("s")
                                break
                        fm = f"---\ntype: {ptype}\ntitle: {md_file.stem}\ncreated: {today}\n---\n\n"
                        md_file.write_text(fm + text, encoding="utf-8")
                        fixed += 1
                except Exception:
                    continue

        return fixed


