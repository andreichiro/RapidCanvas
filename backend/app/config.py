"""Application settings for the Bluesky Contextual Post Explainer.

This module is intentionally executable so T0 can verify configuration loading:

    uv run python -m app.config
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings loaded from environment variables and optional `.env` files."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Bluesky Contextual Post Explainer"
    app_env: Literal["local", "test", "production"] = "local"
    log_level: str = "INFO"
    api_prefix: str = "/api"
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5174",
        ]
    )

    openai_api_key: SecretStr | None = None
    dspy_model: str = "openai/gpt-4.1-mini"
    dspy_judge_model: str = "openai/gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"
    vision_model: str = "gpt-4.1-mini"

    enable_image_understanding: bool = True
    enable_hf_reranker: bool = False

    mlflow_tracking_uri: str = "file:./mlruns"
    qdrant_url: str | None = None
    qdrant_path: str = ".cache/qdrant"
    reports_dir: str = "reports"
    retrieval_max_queries: int = 3
    retrieval_search_limit_per_provider: int = 3
    retrieval_linked_page_limit: int = 3
    enable_rate_limiting: bool = True
    rate_limit_window_seconds: int = 60
    rate_limit_max_explain_requests: int = 120

    anthropic_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    ollama_base_url: str = "http://localhost:11434"

    def safe_dump(self) -> dict[str, Any]:
        """Return settings for logs/diagnostics without revealing secrets."""

        data = self.model_dump(mode="json")
        for key in ("openai_api_key", "anthropic_api_key", "gemini_api_key"):
            if data.get(key):
                data[key] = "**********"
        return data


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()


def main() -> None:
    """Print a sanitized settings payload for T0 verification."""

    print(json.dumps(get_settings().safe_dump(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
