from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLMWIKI_", env_file=".env")

    kb_root: Path = Path("/data/kbs")
    # LLM config
    llm_provider: str = "openai"
    llm_endpoint: str = "http://localhost:11434/v1"
    llm_model: str = "qwen2.5:7b"
    llm_api_key: Optional[str] = None
    llm_thinking: str = "off"       # auto|off|enabled|low|medium|high
    llm_max_tokens: int = 32768

    db_path: Path = Path("data/llmwiki.db")
    host: str = "0.0.0.0"
    port: int = 8742

    # Watcher
    watcher_enabled: bool = True
    watcher_interval_seconds: int = 30

    # Job limits
    max_concurrent_jobs: int = 4
    job_timeout_seconds: int = 3600

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Support bare env vars as fallback (docker-compose compatibility)
        import os
        if os.getenv("KB_ROOT") and not kwargs.get("kb_root"):
            self.kb_root = Path(os.getenv("KB_ROOT"))
        if os.getenv("LLM_ENDPOINT") and not kwargs.get("llm_endpoint"):
            self.llm_endpoint = os.getenv("LLM_ENDPOINT")
        if os.getenv("LLM_MODEL") and not kwargs.get("llm_model"):
            self.llm_model = os.getenv("LLM_MODEL")
        if os.getenv("LLM_API_KEY") and not kwargs.get("llm_api_key"):
            self.llm_api_key = os.getenv("LLM_API_KEY")
        if os.getenv("LLM_PROVIDER") and not kwargs.get("llm_provider"):
            self.llm_provider = os.getenv("LLM_PROVIDER")
        if os.getenv("LLM_THINKING") and not kwargs.get("llm_thinking"):
            self.llm_thinking = os.getenv("LLM_THINKING")


settings = Settings()
