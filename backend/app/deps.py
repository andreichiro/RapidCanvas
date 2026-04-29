"""FastAPI dependency factories and lightweight service registries."""

from __future__ import annotations

from app.agent.dev_adapter import Gate3Explainer
from app.clients.bsky import BlueskyClient
from app.config import Settings, get_settings
from app.schemas.domain import ProviderInfo


def get_provider_catalog(settings: Settings | None = None) -> list[ProviderInfo]:
    """Return provider availability without making network calls."""

    active_settings = settings or get_settings()
    return [
        ProviderInfo(
            name="openai",
            configured=active_settings.openai_api_key is not None,
            skipped_reason=None
            if active_settings.openai_api_key
            else "OPENAI_API_KEY is not configured",
            default_model=active_settings.dspy_model,
        ),
        ProviderInfo(
            name="anthropic",
            configured=active_settings.anthropic_api_key is not None,
            skipped_reason=None
            if active_settings.anthropic_api_key
            else "ANTHROPIC_API_KEY is not configured",
        ),
        ProviderInfo(
            name="gemini",
            configured=active_settings.gemini_api_key is not None,
            skipped_reason=None
            if active_settings.gemini_api_key
            else "GEMINI_API_KEY is not configured",
        ),
        ProviderInfo(
            name="ollama",
            configured=False,
            skipped_reason="Ollama provider is reserved for T8 provider comparison",
        ),
    ]


def build_gate3_explainer() -> Gate3Explainer:
    """Build the current explain service.

    Gate 3 uses real Bluesky fetching and deterministic dev adapters for the
    Search/RAG and DSPy layers. Later gates replace this builder with real
    retrieval and DSPy services.
    """

    return Gate3Explainer(bluesky_client=BlueskyClient())
