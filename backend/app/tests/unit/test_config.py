from __future__ import annotations

from pydantic import SecretStr

from app.config import Settings


def test_settings_defaults_load_without_env() -> None:
    settings = Settings(openai_api_key=None)

    assert settings.app_name == "Bluesky Contextual Post Explainer"
    assert settings.api_prefix == "/api"
    assert settings.embedding_model == "text-embedding-3-small"
    assert settings.enable_image_understanding is True
    assert settings.retrieval_max_queries == 3
    assert settings.retrieval_search_limit_per_provider == 3
    assert settings.retrieval_linked_page_limit == 3
    assert settings.retrieval_linked_page_concurrency == 4
    assert settings.retrieval_search_concurrency == 4
    assert settings.retrieval_timeout_seconds == 25.0


def test_safe_dump_masks_secrets() -> None:
    settings = Settings(
        openai_api_key=SecretStr("openai-test-secret"),
        anthropic_api_key=SecretStr("anthropic-secret"),
        gemini_api_key=SecretStr("gemini-secret"),
    )

    payload = settings.safe_dump()

    assert payload["openai_api_key"] == "**********"
    assert payload["anthropic_api_key"] == "**********"
    assert payload["gemini_api_key"] == "**********"
