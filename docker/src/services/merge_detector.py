"""Merge Detector — find similar crystals/communities, auto-merge or queue for review.

New rules:
  1. Chinese-English same meaning → auto-merge, keep newer
  2. <50% word overlap → keep separate
  3. 50-80% → LLM judges first. If LLM says "merge" → auto. If "review" → user queue.
  4. >80% → auto-merge, keep newer
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import aiosqlite


class MergeDetector:
    def __init__(self, db: aiosqlite.Connection, llm=None):
        self.db = db
        self.llm = llm
        self.tokens_used = 0

    async def detect_and_merge(self, kb_id: str, root_path: str) -> dict:
        """Detect duplicates within same-type items only (crystals vs crystals, communities vs communities)."""
        root = Path(root_path)

        auto_count = 0
        review_candidates = []
        total_collected = 0

        # Process each type independently
        for item_type, directory in [
            ("crystal", root / "wiki" / "crystals"),
            ("community", root / "communities"),
        ]:
            items = self._collect_from_dir(directory, item_type, root)
            total_collected += len(items)
            if len(items) < 2:
                continue

            a, r = await self._detect_in_group(items, root)
            auto_count += a
            review_candidates.extend(r)

        await self._save_review_items(kb_id, review_candidates)

        return {
            "auto_merged": auto_count,
            "review_items": len(review_candidates),
            "skipped": total_collected,
        }

    async def _detect_in_group(self, items: list[dict], root: Path) -> tuple:
        """Run detection on a single type group. Returns (auto_count, review_candidates)."""
        auto_count = 0
        review_candidates = []

        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                overlap = self._overlap(a["content"], b["content"])

                # Rule 1: Chinese-English pairs → always review (unsafe to auto-merge)
                is_cn_en = self._is_same_meaning(a, b)
                if is_cn_en:
                    review_candidates.append(self._make_review_item(a, b, overlap, "cn-en"))
                    continue

                # Rule 2: <35% skip
                if overlap < 0.35:
                    continue

                # Rule 4: >50% auto-merge
                if overlap >= 0.50:
                    self._merge_keep_newer(root, a, b)
                    auto_count += 1
                    continue

                # Rule 3: 35-50% → LLM judgment
                if self.llm:
                    decision = await self._llm_judge(a, b, overlap)
                    if decision == "merge":
                        self._merge_keep_newer(root, a, b)
                        auto_count += 1
                        continue
                    elif decision == "review":
                        review_candidates.append(self._make_review_item(a, b, overlap, "review"))
                    # else: skip
                else:
                    review_candidates.append(self._make_review_item(a, b, overlap, "review"))

        return auto_count, review_candidates

    @staticmethod
    def _collect_from_dir(directory: Path, item_type: str, root: Path) -> list[dict]:
        items = []
        if not directory.exists():
            return items
        for md_file in sorted(directory.rglob("*.md"), key=lambda f: f.stem):
            try:
                text = md_file.read_text(encoding="utf-8")
                fm = MergeDetector._parse_fm(text)
                body = text.split("---", 2)[-1] if text.count("---") >= 2 else text
                items.append({
                    "path": str(md_file.relative_to(root)),
                    "slug": md_file.stem,
                    "title": fm.get("title", fm.get("name", md_file.stem)),
                    "content": body[:3000],
                    "item_type": item_type,
                    "updated": fm.get("updated", ""),
                })
            except Exception:
                pass
        return items

    @staticmethod
    def _is_same_meaning(a: dict, b: dict) -> bool:
        """Detect Chinese-English same-meaning pairs."""
        def has_chinese(s: str) -> bool:
            return bool(re.search(r'[\u4e00-\u9fff]', s))
        a_cn = has_chinese(a["title"])
        b_cn = has_chinese(b["title"])
        # One is Chinese, one is English
        if a_cn == b_cn:
            return False
        # Check content overlap for same-meaning validation
        overlap = MergeDetector._overlap(a["content"][:2000], b["content"][:2000])
        return overlap > 0.15

    @staticmethod
    def _merge_keep_newer(root: Path, a: dict, b: dict) -> None:
        """Delete the older of the two files."""
        file_a = root / a["path"]
        file_b = root / b["path"]
        if not file_a.exists():
            return
        if not file_b.exists():
            return
        # Keep the one with later updated date
        updated_a = str(a.get("updated", ""))
        updated_b = str(b.get("updated", ""))
        if updated_a >= updated_b:
            file_b.unlink(missing_ok=True)
        else:
            file_a.unlink(missing_ok=True)

    async def _llm_judge(self, a: dict, b: dict, overlap: float) -> str:
        """Ask LLM: should these be merged? Returns 'merge', 'review', or 'skip'."""
        prompt = f"""Two knowledge items have {overlap:.0%} content overlap.

Item A ({a['item_type']}): {a['title']}
{a['content'][:1000]}

Item B ({b['item_type']}): {b['title']}
{b['content'][:1000]}

Should they be merged into one? Reply with exactly one word:
- merge: they cover the same topic, merge them
- review: unsure, needs human judgment
- skip: they are different topics, keep separate"""
        try:
            from .token_tracker import TokenTracker
            tracker = TokenTracker()
            result, tokens = await tracker.chat(self.llm, [
                {"role": "system", "content": "Reply with exactly one word: merge, review, or skip."},
                {"role": "user", "content": prompt},
            ], max_tokens=10, temperature=0)
            self.tokens_used += tokens
            result = result.strip().lower()
            if result in ("merge", "review", "skip"):
                return result
        except Exception:
            pass
        return "review"

    async def _save_review_items(self, kb_id: str, items: list[dict]) -> None:
        """Merge new review items with existing ones."""
        key = f"review_queue_{kb_id}"
        async with self.db.execute("SELECT value FROM config WHERE key=?", (key,)) as cur:
            row = await cur.fetchone()
            existing = json.loads(row[0]) if row else []
        # Keep existing resolved IDs
        existing_ids = {i.get("id", "") for i in existing}
        for item in items:
            if item.get("id", "") not in existing_ids:
                existing.append(item)
        await self.db.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            (key, json.dumps(existing, ensure_ascii=False)),
        )
        await self.db.commit()

    @staticmethod
    def _make_review_item(a: dict, b: dict, overlap: float, threshold: str) -> dict:
        s1, s2 = sorted([a['slug'], b['slug']])
        return {
            "id": f"merge-{s1}-vs-{s2}",
            "type": f"{a['item_type']}_merge",
            "threshold": threshold,
            "overlap": round(overlap, 2),
            "item_a": {"path": a["path"], "title": a["title"], "slug": a["slug"], "updated": str(a.get("updated", ""))},
            "item_b": {"path": b["path"], "title": b["title"], "slug": b["slug"], "updated": str(b.get("updated", ""))},
            "created": date.today().isoformat(),
        }

    @staticmethod
    def _parse_fm(text: str) -> dict:
        if not text.startswith("---"):
            return {}
        try:
            end = text.index("---", 3)
            import yaml
            return yaml.safe_load(text[3:end]) or {}
        except Exception:
            return {}

    # Common stopwords to exclude from tokenization
    _STOPWORDS = {
        "the", "this", "that", "these", "those", "and", "with", "for", "from",
        "are", "was", "were", "been", "being", "have", "has", "had", "does",
        "its", "not", "but", "all", "can", "may", "will", "would", "could",
        "about", "also", "into", "than", "then", "only", "other", "more",
        "some", "such", "each", "both", "what", "which", "when", "where",
        "who", "how", "members", "updated", "type", "community", "crystal",
    }

    @staticmethod
    def _tokenize(s: str) -> set:
        # Chinese: 2+ consecutive characters
        # English: 2+ letter words
        # Also capture mixed alphanumeric (e.g. "AI2", "IL-6")
        raw = re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9]|[a-zA-Z]{2,}', s.lower())
        return {t for t in raw if t not in MergeDetector._STOPWORDS and len(t) > 1}

    @staticmethod
    def _overlap(a: str, b: str) -> float:
        ta, tb = MergeDetector._tokenize(a), MergeDetector._tokenize(b)
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / min(len(ta), len(tb))
