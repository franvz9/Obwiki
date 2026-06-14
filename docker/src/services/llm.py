"""LLM Client — thin wrapper. For multi-provider support use llm_providers."""

from __future__ import annotations

from typing import Optional

from .llm_providers import create_provider, provider_chat, ProviderConfig


class LLMClient:
    """Backward-compatible LLM client. Auto-detects endpoint type."""

    def __init__(
        self,
        endpoint: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        provider: str = "openai",
    ):
        from ..config import settings
        self.endpoint = endpoint or settings.llm_endpoint
        self.model = model or settings.llm_model
        self.api_key = api_key or settings.llm_api_key
        self.provider_name = provider

        # Detect provider from endpoint
        ep_lower = self.endpoint.lower()
        if "deepseek.com" in ep_lower:
            self.provider_name = "deepseek"
        elif "anthropic.com" in ep_lower:
            self.provider_name = "anthropic"
        elif "openai.com" in ep_lower:
            self.provider_name = "openai"
        elif any(h in ep_lower for h in ("localhost", "127.0.0.1", "ollama")):
            self.provider_name = "ollama"

        self._cfg: Optional[ProviderConfig] = None

    def _get_cfg(self) -> ProviderConfig:
        if self._cfg is None:
            self._cfg = create_provider(
                provider=self.provider_name,
                endpoint=self.endpoint,
                api_key=self.api_key or "",
                model=self.model,
            )
        return self._cfg

    async def chat(self, messages: list[dict], **kwargs) -> str:
        """Backward-compatible: returns text only. Use chat_with_usage() for token info."""
        text, _ = await self.chat_with_usage(messages, **kwargs)
        return text

    async def chat_with_usage(self, messages: list[dict], **kwargs) -> tuple[str, dict]:
        cfg = self._get_cfg()
        if self.provider_name == "deepseek" and "thinking" not in kwargs:
            kwargs["thinking"] = "off"
        return await provider_chat(cfg, messages, **kwargs)


def get_llm(endpoint=None, model=None, api_key=None, provider="openai") -> LLMClient:
    return LLMClient(endpoint=endpoint, model=model, api_key=api_key, provider=provider)
