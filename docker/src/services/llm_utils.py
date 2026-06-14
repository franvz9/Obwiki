"""Shared LLM output utilities — JSON extraction and text cleaning."""

from __future__ import annotations

import json
import re


def clean_json(text: str) -> str:
    """Extract valid JSON from LLM output that may contain reasoning/CoT or markdown fences."""
    text = text.strip()
    # Remove outermost markdown fences
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:]) if len(lines) > 1 else text
    if text.endswith("```"):
        text = text[:-3].strip()
    # For reasoning models: find the LAST valid JSON object (CoT before, answer at the end)
    for m in reversed(list(re.finditer(r'\{', text))):
        candidate = text[m.start():]
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            continue
    return text
