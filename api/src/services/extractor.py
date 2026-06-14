from __future__ import annotations
from ..paths import INBOX_DIR, META_DIR, WIKI_DIR, COMMUNITIES_DIR, LLMWIKI_DIR, OPS_DIR, INDEX_FILE, OVERVIEW_FILE, LOG_FILE, SCHEMA_FILE, CACHE_DIR

import hashlib
import json

from pathlib import Path

import aiosqlite
import yaml

from .llm import LLMClient
from .parsers import parse_document

# ── Two-Step Chain-of-Thought prompts ──
# Step 1 (Analysis): LLM reads source → structured analysis
# Step 2 (Generation): LLM takes analysis → wiki files + review items
# Inspired by nashsu/llm_wiki's buildAnalysisPrompt + buildGenerationPrompt

ANALYSIS_PROMPT = """You are an expert research analyst. Read the source document and produce a structured analysis.
Do not output chain-of-thought, hidden reasoning, or a thinking transcript. Reason internally and write only the concise final analysis.

**CRITICAL — Language**: Write in the SAME language as the source document. Do NOT translate. If the source is Chinese, output Chinese. If English, output English.

**CRITICAL — Existing Nodes**: If a concept/entity already exists in the wiki (even in a different language with the same meaning), link to it via [[wikilink]]. Do NOT create duplicate pages for the same entity in different languages.

Your analysis should cover:

## Key Entities
List people, organizations, products, datasets, tools mentioned. For each:
- Name and type
- Role in the source (central vs. peripheral)
- Whether it likely already exists in the wiki (check the index)

## Key Concepts
List theories, methods, techniques, phenomena. For each:
- Name and brief definition
- Why it matters in this source
- Whether it likely already exists in the wiki

## Main Arguments & Findings
- What are the core claims or results?
- What evidence supports them?
- How strong is the evidence?

## Connections to Existing Wiki
- What existing pages does this source relate to?
- Does it strengthen, challenge, or extend existing knowledge?

## Contradictions & Tensions
- Does anything in this source conflict with existing wiki content?
- Are there internal tensions or caveats?

## Document Classification
Classify the source into ONE category:
- paper: Academic/research paper with abstract, methods, results, references
- document: Reports, proposals, specifications, general formal documents
- notes: Personal notes, meeting notes, brainstorming, informal writing
- conversation: AI chat exports, conversation logs, Q&A records
- memory: AI agent memory dumps, structured knowledge records
- data: Structured data, tables, spreadsheets, CSVs
- other: None of the above

Output: {{"class": "<category>"}}

## Recommendations
- What wiki pages should be created or updated?
- What should be emphasized vs. de-emphasized?
- Any open questions worth flagging for the user?

Be thorough but concise. Focus on what's genuinely important.

If a folder context is provided, use it as a hint for categorization — the folder structure often reflects the user's organizational intent.

## Wiki Purpose (for context)
{purpose}

## Current Wiki Index (for checking existing content)
{wiki_index}"""


GENERATION_PROMPT = """You are a wiki maintainer. Based on the analysis provided, generate wiki files.
Do not output chain-of-thought, hidden reasoning, or explanatory preamble. Reason internally and output only the requested FILE/REVIEW blocks.

**CRITICAL — Language**: Write in the SAME language as the source document. Do NOT auto-translate.

**CRITICAL — Dedup**: Check the wiki index for existing pages with the same meaning (even in different languages). Use [[wikilink]] to existing pages. Do NOT create duplicate entity/concept pages when a synonym exists.

**CRITICAL — Wikilink format**: Wikilinks MUST use paths relative to wiki/ directory, e.g. [[entities/PageName]] NOT [[wiki/entities/PageName]].

**CRITICAL — No wikilinks in meta files**: _meta/_index.md, _meta/_overview.md, and operations/log.md MUST use plain text paths. NEVER use [[wikilinks]] in these files — they create unwanted graph centralization hubs.

## IMPORTANT: Source File
The original source file is: **{source_filename}**
All wiki pages generated from this source MUST include this filename in their frontmatter `sources` field.
Today's date is **{today}**. Use this exact date for all new `created`, `updated`, and log dates.

{purpose_section}

## What to generate

1. A source summary page at **wiki/sources/{source_basename}.md** — This is the most important page. It MUST contain:
   - A 2-4 paragraph overview summarizing the document's main topic, purpose, and scope
   - Key findings or conclusions (bullet list)
   - Methodology or approach used (if applicable)
   - Links to all entity and concept pages generated from this source
   - The original filename and document type
2. Entity pages for key named things identified in the analysis: wiki/entities/
3. Concept pages for key ideas, methods, techniques: wiki/concepts/
4. An updated index at **_meta/_index.md** — add new entries, preserve all existing ones (underscore prefix keeps it hidden from Obsidian graph)
5. A log entry for **operations/log.md** (just the new entry: ## [YYYY-MM-DD] ingest | Title)
6. An updated overview at **_meta/_overview.md** — comprehensive 2-5 paragraph overview of ALL topics (underscore prefix keeps it hidden from Obsidian graph)

## Frontmatter Rules (CRITICAL — parser is strict)

Every page begins with a YAML frontmatter block. Required fields:
- type: source_summary | entity | concept | synthesis | comparison | crystal
- title: string
- sources: array of source file paths (for the source summary, just the source filename)
- created: YYYY-MM-DD
- updated: YYYY-MM-DD (same as created for new pages)
- tags: array of strings

Format exactly like this (NO nested quotes in yaml values):
```
---
type: concept
title: Title Here
sources:
- raw/sources/filename.pdf
created: {today}
updated: {today}
tags:
- tag1
- tag2
---

Page content here...
```

## Wikilinks
Use [[path/to/page]] for cross-references between wiki pages. Use forward slashes.

## Existing wiki index
{wiki_index}

## Existing wiki overview
{overview}

## Analysis
{analysis_json}

Generate pages in this format. For each page output exactly:

```
<<<FILE: wiki/path/to/page.md>>>
(frontmatter + content here)
<<<END>>>
```

Then output review items:

```
<<<REVIEW>>>
- action: create_page | deep_research | skip
  title: item title
  description: why it needs review
  search_queries:
  - query 1
  - query 2
<<<END>>>
```"""

PURPOSE_TEMPLATE = """## Wiki Purpose
This wiki serves as a knowledge base for: {purpose}"""


class Extractor:
    def __init__(self, db: aiosqlite.Connection, llm: LLMClient, source_registry=None):
        self.db = db
        self.llm = llm
        self.sr = source_registry

    async def extract(self, kb_id: str, root_path: str,
                      source_paths: list[str] | None = None,
                      purpose: str = "", force_text: bool = False) -> dict:
        root = Path(root_path)
        raw_dir = root / INBOX_DIR
        from .wiki_schema import find_wiki_dir; wiki_dir = find_wiki_dir(root)

        if not raw_dir.exists():
            return {"status": "no raw directory"}

        # Load schema for page routing
        from .wiki_schema import parse_schema, write_default_schema
        schema_path = root / META_DIR / "schema.md"
        if not schema_path.exists():
            write_default_schema(str(root))
        schema = parse_schema(str(root))

        # Create wiki directories from schema
        wiki_dir.mkdir(parents=True, exist_ok=True)
        for t in schema.types:
            d = root / t["directory"]
            d.mkdir(parents=True, exist_ok=True)

        # Read purpose from config
        if not purpose:
            config_path = root / ".llmwiki" / "config.yaml"
            if config_path.exists():
                try:
                    config = yaml.safe_load(config_path.read_text()) or {}
                    purpose = config.get("purpose", "")
                except Exception:
                    pass

        # Determine which files to process
        if source_paths:
            files = [raw_dir / p for p in source_paths]
        else:
            # Use SourceRegistry to find pending files
            if self.sr:
                pending = await self.sr.get_pending(kb_id)
                files = [root / p["path"] for p in pending if (root / p["path"]).exists()]
            else:
                files = []
                for ext in ("*.md", "*.pdf", "*.docx", "*.pptx", "*.xlsx", "*.txt",
                             "*.html", "*.csv", "*.json"):
                    files.extend(f for f in raw_dir.rglob(ext) if ".cache" not in f.parts)

        results = {"processed": 0, "skipped": 0, "pages_created": [], "errors": [], "tokens": 0}
        import asyncio
        sem = asyncio.Semaphore(2)  # Max 2 concurrent file extractions

        async def process_one(src_file: Path) -> None:
            nonlocal results
            if not src_file.exists(): return

            rel = str(src_file.relative_to(root))

            # Skip if already extracted
            if self.sr:
                src_info = await self.sr.get(kb_id, rel)
                if src_info and src_info["status"] == "extracted":
                    try:
                        if hashlib.sha256(parse_document(str(src_file)).encode()).hexdigest() == src_info["content_hash"]:
                            results["skipped"] += 1; return
                    except Exception: pass

            try: content = parse_document(str(src_file))
            except Exception as e:
                results["errors"].append({"file": str(src_file), "error": f"parse: {e}"})
                if self.sr: await self.sr.set_status(kb_id, rel, "error", str(e))
                return

            # Image check
            if src_file.suffix.lstrip(".").lower() in ("pdf", "docx", "pptx", "ppt") and not force_text:
                from .model_registry import extract_images_from_file, is_vision_model
                try:
                    from .provider_service import ProviderService
                    vis = await ProviderService(self.db).get_default_vision()
                    if not (vis and vis.get("models")):
                        images = extract_images_from_file(str(src_file))
                        if images and not is_vision_model(self.llm.model):
                            results["errors"].append({"file": str(src_file), "error": f"DOC_HAS_IMAGES:{len(images)}_images_found"})
                            if self.sr: await self.sr.set_status(kb_id, rel, "error", f"{len(images)} images, no vision model")
                            return
                except Exception: pass

            if self.sr: await self.sr.set_status(kb_id, rel, "extracting")

            async with sem:
                try:
                    pages, tokens = await self._process_source(kb_id, root, src_file, content, wiki_dir, purpose, schema)
                    results["processed"] += 1
                    results["pages_created"].extend(pages)
                    results["tokens"] += tokens
                    if self.sr:
                        await self.sr.set_status(kb_id, rel, "extracted")
                        await self.sr.record_wiki_pages(kb_id, rel, pages)
                except Exception as e:
                    results["errors"].append({"file": str(src_file), "error": str(e)})
                    if self.sr: await self.sr.set_status(kb_id, rel, "error", str(e))

        await asyncio.gather(*[process_one(f) for f in files])
        await self._rebuild_index(wiki_dir)
        return results

    async def _process_source(self, kb_id: str, root: Path, src_file: Path,
                               content: str, wiki_dir: Path, purpose: str,
                               schema=None) -> tuple[list[str], int]:
        wiki_index = await self._read_index(wiki_dir)
        overview = await self._read_overview(wiki_dir)
        rel = str(src_file.relative_to(root))

        # Check if content is long enough to warrant chunking
        from .model_registry import lookup as _lookup_model
        model_spec = _lookup_model(self.llm.model)
        threshold = model_spec.chunk_threshold
        estimated_tokens = len(content) * 1.5  # rough estimate for CJK text

        if estimated_tokens > threshold:
            return await self._process_chunked(
                kb_id, root, src_file, content, wiki_dir, purpose, schema,
                wiki_index, overview, rel, model_spec,
            )

        return await self._process_single(
            src_file, content, wiki_dir, purpose, schema,
            wiki_index, overview, rel, root,
        )

    async def _process_single(self, src_file: Path, content: str,
                               wiki_dir: Path, purpose: str, schema,
                               wiki_index: str, overview: str, rel: str,
                               root: Path = Path("."),
                               ) -> tuple[list[str], int]:

        # Step 1: Analysis
        analysis, usage1 = await self.llm.chat_with_usage([
            {"role": "system", "content": "You are a precise knowledge extraction analyst. Output only the structured analysis, no markdown fences."},
            {"role": "user", "content": ANALYSIS_PROMPT.format(
                purpose=purpose or "General knowledge accumulation",
                wiki_index=wiki_index[:4000],
            )},
            {"role": "user", "content": f"Analyze this source document:\n\n**File:** {rel}\n\n---\n\n{content[:16000]}"},
        ])
        tokens = usage1.get("total_tokens", 0)

        # Step 2: Generation
        from datetime import date
        today = date.today().isoformat()

        generation, usage2 = await self.llm.chat_with_usage([
            {"role": "system", "content": "You are a precise wiki editor. Output only FILE/REVIEW blocks, no other text."},
            {"role": "user", "content": GENERATION_PROMPT.format(
                source_filename=rel,
                source_basename=src_file.stem,
                today=today,
                purpose_section=PURPOSE_TEMPLATE.format(purpose=purpose) if purpose else "",
                wiki_index=wiki_index[:3000],
                overview=overview[:2000],
                analysis_json=analysis[:8000],
            )},
        ])
        tokens += usage2.get("total_tokens", 0)

        pages = await self._write_generated_pages(root, wiki_dir, generation, rel, today)
        # Ensure source summary page exists + append original text
        await self._ensure_source_page(root, src_file, rel, pages, today, content)
        return pages, tokens

    async def _process_chunked(
        self, kb_id: str, root: Path, src_file: Path, content: str,
        wiki_dir: Path, purpose: str, schema,
        wiki_index: str, overview: str, rel: str, model_spec,
    ) -> tuple[list[str], int]:
        """Process a long document by splitting into chunks, each round passing prior context."""
        chunks = self._split_content(content, model_spec.safe_chunk_size)
        total_tokens = 0
        merged_analysis = ""
        today = __import__("datetime").date.today().isoformat()

        for i, chunk in enumerate(chunks):
            is_last = (i == len(chunks) - 1)
            context_prefix = ""
            if i > 0 and merged_analysis:
                context_prefix = (
                    f"This is part {i+1} of {len(chunks)} from the same document.\n"
                    f"Previous parts analysis summary:\n{merged_analysis[:2000]}\n\n"
                )

            # Step 1: Analyze this chunk
            analysis, u1 = await self.llm.chat_with_usage([
                {"role": "system", "content": "You are a precise knowledge extraction analyst."},
                {"role": "user", "content": ANALYSIS_PROMPT.format(
                    purpose=purpose or "General knowledge accumulation",
                    wiki_index=wiki_index[:3000],
                )},
                {"role": "user", "content": (
                    f"{context_prefix}"
                    f"Analyze this document chunk:\n\n"
                    f"**File:** {rel} (part {i+1}/{len(chunks)})\n\n---\n{chunk}"
                )},
            ])
            total_tokens += u1.get("total_tokens", 0)

            # Merge analysis
            if i == 0:
                merged_analysis = analysis
            else:
                # LLM merges previous + new analysis
                merge_prompt = (
                    f"You have analyzed multiple parts of the same document. "
                    f"Merge the following two analyses into one coherent analysis. "
                    f"Combine entities, concepts, and claims. Resolve contradictions.\n\n"
                    f"## Previous merged analysis\n{merged_analysis[:3000]}\n\n"
                    f"## New chunk analysis\n{analysis[:3000]}\n\n"
                    f"Output the merged analysis in the same format."
                )
                merged, u2 = await self.llm.chat_with_usage([
                    {"role": "system", "content": "Merge analyses. Output only the merged analysis."},
                    {"role": "user", "content": merge_prompt},
                ])
                merged_analysis = merged
                total_tokens += u2.get("total_tokens", 0)

        # Final step: generate wiki pages from merged analysis
        generation, u3 = await self.llm.chat_with_usage([
            {"role": "system", "content": "You are a precise wiki editor. Output only FILE/REVIEW blocks."},
            {"role": "user", "content": GENERATION_PROMPT.format(
                source_filename=rel,
                source_basename=src_file.stem,
                today=today,
                purpose_section=PURPOSE_TEMPLATE.format(purpose=purpose) if purpose else "",
                wiki_index=wiki_index[:3000],
                overview=overview[:2000],
                analysis_json=merged_analysis[:8000],
            )},
        ])
        total_tokens += u3.get("total_tokens", 0)

        pages = await self._write_generated_pages(root, wiki_dir, generation, rel, today)
        await self._ensure_source_page(root, src_file, rel, pages, today, content)
        return pages, total_tokens

    @staticmethod
    def _split_content(content: str, max_chars: int) -> list[str]:
        """Split content by ## headings, keeping chunks under max_chars.
        max_chars derived from model_spec.safe_chunk_size / 1.5 (rough token→char conversion)."""
        max_chars = int(max_chars / 1.5)  # tokens → chars
        sections = content.split("\n## ")
        chunks = []
        current = sections[0] if sections else ""

        for section in sections[1:]:
            section = "## " + section
            if len(current) + len(section) > max_chars:
                chunks.append(current)
                current = section
            else:
                current += "\n" + section
        if current.strip():
            chunks.append(current)
        return [c for c in chunks if c.strip()]

    async def _write_generated_pages(self, root: Path, wiki_dir: Path,
                                      generation: str, source_rel: str, today: str) -> list[str]:
        created = []
        current_page = None
        current_content = []
        review_items = []

        in_review = False
        for line in generation.split("\n"):
            line_stripped = line.strip()
            if line_stripped.startswith("<<<FILE:") and ">>>" in line_stripped:
                if current_page and current_content:
                    saved = await self._save_page(root, current_page, "\n".join(current_content))
                    if saved:
                        created.append(saved)
                    current_page = None
                    current_content = []
                # Extract path between <<<FILE: and >>>
                tag_part = line_stripped[len("<<<FILE:"):]
                tag_part = tag_part.split(">>>")[0].strip()
                current_page = tag_part
                current_content = []
                in_review = False
            elif line_stripped.startswith("<<<REVIEW>>>"):
                if current_page and current_content:
                    await self._save_page(root, current_page, "\n".join(current_content))
                    created.append(current_page)
                current_page = None
                current_content = []
                in_review = True
            elif line_stripped.startswith("<<<END>>>"):
                if not in_review and current_page is None:
                    current_page = None
                in_review = False
            elif current_page is not None:
                current_content.append(line)
            elif in_review:
                review_items.append(line_stripped)

        # Save last page
        if current_page and current_content:
            saved = await self._save_page(root, current_page, "\n".join(current_content))
            if saved:
                created.append(saved)

        # Append log entry
        log_path = root / OPS_DIR / "log.md"
        log_dir = log_path.parent
        log_dir.mkdir(parents=True, exist_ok=True)
        existing = log_path.read_text(encoding="utf-8") if log_path.exists() else "# Operation Log\n\n"
        log_entry = f"## [{today}] ingest | {source_rel}\n\n- Created: {len(created)} pages\n"
        log_path.write_text(existing + log_entry + "\n", encoding="utf-8")

        return created

    async def _save_page(self, root: Path, path: str, content: str) -> str | None:
        full_path = root / path
        slug = full_path.stem.lower().replace("-", " ")
        # Check FTS5 for similar existing pages
        existing = await self._find_similar_page(slug)
        if existing:
            sim = self._title_similarity(slug, existing.lower().replace("-", " "))
            if sim > 0.8:
                return None  # too similar, skip creation
            if sim > 0.5:
                content = content.rstrip() + f"\n\n> See also: [[{existing}]]\n"
                exist_path = root / existing
                if exist_path.exists():
                    try:
                        ec = exist_path.read_text(encoding="utf-8")
                        if f"[[{path}]]" not in ec:
                            exist_path.write_text(ec.rstrip() + f"\n\n> See also: [[{path}]]\n", encoding="utf-8")
                    except Exception:
                        pass
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        return path

    @staticmethod
    def _title_similarity(a: str, b: str) -> float:
        import re
        ta = set(re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z]{2,}', a.lower()))
        tb = set(re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z]{2,}', b.lower()))
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / min(len(ta), len(tb))

    async def _find_similar_page(self, title_slug: str) -> str | None:
        try:
            async with self.db.execute(
                "SELECT path FROM files_fts WHERE files_fts MATCH ? LIMIT 5",
                (title_slug.replace(" ", " OR "),),
            ) as cursor:
                rows = [row["path"] async for row in cursor]
                best, best_sim = None, 0.0
                from pathlib import Path
                for r in rows:
                    stem = Path(r).stem.lower().replace("-", " ")
                    sim = self._title_similarity(title_slug, stem)
                    if sim > best_sim:
                        best_sim, best = sim, r
                return best if best and best_sim > 0.5 else None
        except Exception:
            return None

    async def _get_cache(self, kb_id: str, path: str) -> str | None:
        async with self.db.execute(
            "SELECT content_hash FROM file_hashes WHERE kb_id = ? AND path = ?", (kb_id, path)
        ) as cursor:
            row = await cursor.fetchone()
            return row["content_hash"] if row else None

    async def _set_cache(self, kb_id: str, path: str, file_hash: str) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO file_hashes (kb_id, path, content_hash) VALUES (?, ?, ?)",
            (kb_id, path, file_hash),
        )
        await self.db.commit()

    async def _read_index(self, wiki_dir: Path) -> str:
        p = wiki_dir.parent / META_DIR / INDEX_FILE
        return p.read_text(encoding="utf-8") if p.exists() else "# Wiki Index\n\n(empty)"

    async def _read_overview(self, wiki_dir: Path) -> str:
        p = wiki_dir.parent / META_DIR / OVERVIEW_FILE
        return p.read_text(encoding="utf-8") if p.exists() else "# Overview\n\n(empty)"

    async def _ensure_source_page(self, root: Path, src_file: Path, src_rel: str,
                                   pages: list[str], today: str,
                                   original_text: str = "") -> None:
        """If the LLM didn't create a source summary page, auto-generate one. Appends full text to existing source page."""
        expected = f"wiki/sources/{src_file.stem}.md"
        full_path = root / expected

        # Append full text section to existing or new source page
        if any(expected in p for p in pages):
            # Source page exists — append original full text if not already there
            if original_text and full_path.exists():
                existing = full_path.read_text(encoding="utf-8")
                if "## 原始文本" not in existing:
                    text_preview = original_text[:50000]
                    full_path.write_text(existing.rstrip() + f"\n\n## 原始文本\n\n{text_preview}\n", encoding="utf-8")
            return

        # No source page — create one with summary + full text
        text_section = ""
        if original_text:
            text_preview = original_text[:50000]
            text_section = f"\n## 原始文本\n\n{text_preview}\n"
        else:
            text_section = "\n*（原始文本不可用）*\n"

        content = f"""---
type: source_summary
title: {src_file.stem}
sources:
- {src_rel}
created: {today}
updated: {today}
tags:
- source
---

# {src_file.stem}

Source file: {src_rel}
{text_section}
"""
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        pages.append(expected)

    async def _rebuild_index(self, wiki_dir: Path) -> None:
        """Rebuild index.md at KB root (not inside wiki/ to avoid graph centralization)."""
        try:
            root = wiki_dir.parent
            entries = []
            for md_file in sorted(wiki_dir.rglob("*.md")):
                rel = md_file.relative_to(wiki_dir)
                try:
                    text = md_file.read_text(encoding="utf-8")
                    first_line = ""
                    in_fm = False
                    for line in text.split("\n"):
                        ls = line.strip()
                        if ls == "---":
                            in_fm = not in_fm
                            continue
                        if not in_fm and ls and not ls.startswith("#"):
                            first_line = ls.lstrip("# ").strip()
                            break
                    # Strip wikilinks BEFORE truncating
                    import re as _re
                    first_line = _re.sub(r'\[\[.*?\]\]', '', first_line)
                    first_line = _re.sub(r'\[\[[^\]]*$', '', first_line)
                    first_line = first_line.strip()[:80]
                    entries.append(f"- {rel.with_suffix('')}.md — {first_line}")
                except Exception:
                    entries.append(f"- {rel.with_suffix('')}.md")

            index = f"# Wiki Index\n\n*Last updated: {_today_str()}*\n\n" + "\n".join(entries) + "\n"
            # Strip any remaining wikilinks (safety net)
            import re as _re2
            index = _re2.sub(r'\[\[[^\]]*\]\]', lambda m: m.group(0).strip('[]'), index)
            dest = root / META_DIR / INDEX_FILE
            dest.write_text(index, encoding="utf-8")
        except Exception:
            pass  # don't block extract if index rebuild fails


def _today_str() -> str:
    from datetime import date
    return date.today().isoformat()
