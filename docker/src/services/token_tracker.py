"""Shared token tracking — use with LLM calls to avoid double-counting.

Usage:
    tracker = TokenTracker()
    text, tokens = await tracker.chat(llm, messages, **kwargs)
    # 'tokens' is the total_tokens for this call
"""

from __future__ import annotations


class TokenTracker:
    """Wraps an LLMClient to track token usage from chat_with_usage()."""

    def __init__(self):
        self._total = 0

    @property
    def total(self) -> int:
        return self._total

    async def chat(self, llm, messages: list[dict], **kwargs) -> tuple[str, int]:
        """Call LLM and return (response_text, tokens_used_for_this_call)."""
        text, usage = await llm.chat_with_usage(messages, **kwargs)
        tokens = usage.get("total_tokens", 0)
        self._total += tokens
        return text, tokens
