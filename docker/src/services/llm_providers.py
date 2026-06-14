"""Multi-provider LLM backend. Each provider defines URL construction,
request body building, and stream parsing — pluggable, no branching.

Pattern from nashsu/llm_wiki src/lib/llm-providers.ts

Supported providers:
  openai      — api.openai.com, plus all /v1/chat/completions clones
  anthropic   — api.anthropic.com, plus Anthropic-wire clones (MiniMax, etc.)
  deepseek    — api.deepseek.com (OpenAI-wire + thinking control)
  ollama      — localhost:11434 (OpenAI-wire + reasoning_effort)
  custom      — user-provided endpoint with apiMode selection
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import httpx
import json


# ── Types ──────────────────────────────────────────────────────

@dataclass
class ProviderConfig:
    name: str
    url: str
    headers: dict
    model: str
    timeout: int = 600

    def build_body(self, messages: list[dict], **kwargs) -> dict:
        from .model_registry import lookup
        spec = lookup(self.model)
        default_max = int(spec.max_output * 0.8) if spec else 32768
        return {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.3),
            "max_tokens": kwargs.get("max_tokens", default_max),
        }

    def parse_response(self, data: dict) -> str:
        msg = data["choices"][0]["message"]
        content = msg.get("content", "") or ""
        if not content:
            content = msg.get("reasoning_content", "") or ""
        return content

    def extract_usage(self, data: dict) -> dict:
        u = data.get("usage", {})
        return {
            "prompt_tokens": u.get("prompt_tokens", 0),
            "completion_tokens": u.get("completion_tokens", 0),
            "total_tokens": u.get("total_tokens", 0),
        }


# ── Provider factories ─────────────────────────────────────────

def openai(api_key: str, model: str = "gpt-4o") -> ProviderConfig:
    from .model_registry import lookup
    spec = lookup(model)
    return ProviderConfig(
        name="openai",
        url="https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        model=model,
    )


def anthropic(api_key: str, model: str = "claude-sonnet-4-6") -> ProviderConfig:
    from .model_registry import lookup
    spec = lookup(model)
    url = "https://api.anthropic.com/v1/messages"
    return ProviderConfig(
        name="anthropic",
        url=url,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
            "anthropic-dangerous-direct-browser-access": "true",
        },
        model=model,
    )


def deepseek(api_key: str, model: str = "deepseek-v4-pro") -> ProviderConfig:
    cfg = ProviderConfig(
        name="deepseek",
        url="https://api.deepseek.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        model=model,
    )
    # Override build_body to inject thinking=disabled for non-reasoning tasks
    _orig_build = cfg.build_body

    def _build(messages, **kwargs):
        body = _orig_build(messages, **kwargs)
        thinking_mode = kwargs.get("thinking", "auto")
        if thinking_mode == "off":
            body["thinking"] = {"type": "disabled"}
        elif thinking_mode == "enabled":
            body["thinking"] = {"type": "enabled"}
        return body

    cfg.build_body = _build
    return cfg


def ollama(endpoint: str = "http://localhost:11434", model: str = "qwen2.5:7b") -> ProviderConfig:
    base = endpoint.rstrip("/").replace("/v1", "").replace("/v1/chat/completions", "")
    cfg = ProviderConfig(
        name="ollama",
        url=f"{base}/v1/chat/completions",
        headers={"Content-Type": "application/json", "Origin": "http://localhost"},
        model=model,
        timeout=600,
    )
    _orig_build = cfg.build_body

    def _build(messages, **kwargs):
        body = _orig_build(messages, **kwargs)
        thinking_mode = kwargs.get("thinking", "auto")
        if thinking_mode == "off":
            body["reasoning_effort"] = "none"
        elif thinking_mode in ("low", "medium", "high", "max"):
            body["reasoning_effort"] = "high" if thinking_mode == "max" else thinking_mode
        return body

    cfg.build_body = _build
    return cfg


def custom(endpoint: str, api_key: str = "", model: str = "",
           api_mode: str = "chat_completions") -> ProviderConfig:
    """api_mode: 'chat_completions' (OpenAI wire) or 'anthropic_messages' (Anthropic wire)."""
    base = endpoint.rstrip("/")

    if api_mode == "anthropic_messages":
        url = base if "/messages" in base else f"{base}/v1/messages"
        return ProviderConfig(
            name="custom-anthropic",
            url=url,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            model=model,
            timeout=600,
        )

    # Default: OpenAI wire
    url = base if "/chat/completions" in base else f"{base}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return ProviderConfig(
        name="custom",
        url=url,
        headers=headers,
        model=model,
        timeout=600,
    )


# ── Anthropic-specific body builder ────────────────────────────

def _build_anthropic_body(cfg: ProviderConfig, messages: list[dict], **kwargs) -> dict:
    """Build Anthropic Messages API request body."""
    system = None
    chat_msgs = []
    for m in messages:
        if m["role"] == "system":
            system = m["content"]
        else:
            chat_msgs.append({"role": m["role"], "content": m["content"]})

    body: dict = {
        "model": cfg.model,
        "messages": chat_msgs,
        "max_tokens": kwargs.get("max_tokens", 32768),
        "temperature": kwargs.get("temperature", 0.3),
    }
    if system:
        body["system"] = system
    return body


def _parse_anthropic_response(data: dict) -> str:
    """Extract text from Anthropic response."""
    content = data.get("content", [])
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content)
    return str(content)


# ── Factory function ───────────────────────────────────────────

def create_provider(
    provider: str = "openai",
    endpoint: str = "",
    api_key: str = "",
    model: str = "",
    api_mode: str = "chat_completions",
) -> ProviderConfig:
    """Create a ProviderConfig from simple parameters.
    Auto-detects max_tokens from model registry (80% of model's max_output).

    Args:
        provider: 'openai' | 'anthropic' | 'deepseek' | 'ollama' | 'custom'
        endpoint: custom endpoint URL (required for ollama/custom)
        api_key: API key
        model: model name
        api_mode: for custom: 'chat_completions' or 'anthropic_messages'
    """
    from .model_registry import lookup as _lookup_model
    spec = _lookup_model(model) if model else None
    safe_output = int(spec.max_output * 0.8) if spec else 32768

    match provider:
        case "openai":
            return openai(api_key, model or "gpt-4o")
        case "anthropic":
            cfg = anthropic(api_key, model or "claude-sonnet-4-6")
            cfg.build_body = lambda msgs, **kw: _build_anthropic_body(cfg, msgs, **kw)
            cfg.parse_response = _parse_anthropic_response
            return cfg
        case "deepseek":
            return deepseek(api_key, model or "deepseek-v4-pro")
        case "ollama":
            return ollama(endpoint or "http://localhost:11434", model or "qwen2.5:7b")
        case "custom":
            return custom(endpoint, api_key, model, api_mode)
        case _:
            raise ValueError(f"Unknown provider: {provider}")


# ── Chat function ──────────────────────────────────────────────

async def provider_chat(cfg: ProviderConfig, messages: list[dict], **kwargs) -> tuple[str, dict]:
    """Send chat request. Returns (response_text, usage_info)."""
    body = cfg.build_body(messages, **kwargs)

    async with httpx.AsyncClient(timeout=cfg.timeout) as client:
        resp = await client.post(cfg.url, headers=cfg.headers, json=body)
        resp.raise_for_status()
        data = resp.json()
        text = cfg.parse_response(data)
        usage = cfg.extract_usage(data)
        return text, usage
