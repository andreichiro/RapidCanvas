"""Provider selection helpers for DSPy-backed explanation runs."""

from __future__ import annotations

import os
from dataclasses import dataclass

from pydantic import SecretStr

from app.config import Settings


@dataclass(frozen=True)
class ProviderConfig:
    """Resolved model-provider configuration without exposing secret values."""

    name: str
    model: str
    env_var: str
    api_key: SecretStr | None
    configured: bool
    skipped_reason: str | None = None


@dataclass(frozen=True)
class ProviderResolution:
    """Selected provider plus non-fatal warnings for trace output."""

    requested: str
    selected: ProviderConfig
    warnings: tuple[str, ...] = ()


SUPPORTED_PROVIDERS = ("openai", "anthropic", "gemini")


def resolve_provider(
    settings: Settings,
    requested_provider: str | None = None,
) -> ProviderResolution:
    """Resolve a requested provider, falling back to OpenAI when safe to skip."""

    requested = _normalize_provider(requested_provider)
    openai = _provider_config(settings, "openai")
    if requested not in SUPPORTED_PROVIDERS:
        return ProviderResolution(
            requested=requested,
            selected=openai,
            warnings=(f"provider_{requested}_unknown_using_openai",),
        )

    requested_config = _provider_config(settings, requested)
    if requested_config.configured:
        return ProviderResolution(requested=requested, selected=requested_config)

    skip_warning = f"provider_{requested}_skipped:{requested_config.skipped_reason}"
    if requested != "openai" and openai.configured:
        return ProviderResolution(
            requested=requested,
            selected=openai,
            warnings=(skip_warning, "provider_openai_default_used"),
        )
    return ProviderResolution(
        requested=requested,
        selected=requested_config,
        warnings=(skip_warning,),
    )


def export_provider_key(provider: ProviderConfig) -> None:
    """Export the resolved provider key for DSPy without returning the secret."""

    if provider.api_key is None:
        return
    os.environ[provider.env_var] = provider.api_key.get_secret_value()


def _provider_config(settings: Settings, provider: str) -> ProviderConfig:
    if provider == "anthropic":
        return ProviderConfig(
            name="anthropic",
            model=_provider_model(
                settings.dspy_model,
                "anthropic",
                "anthropic/claude-3-5-sonnet-latest",
            ),
            env_var="ANTHROPIC_API_KEY",
            api_key=settings.anthropic_api_key,
            configured=settings.anthropic_api_key is not None,
            skipped_reason="ANTHROPIC_API_KEY is not configured"
            if settings.anthropic_api_key is None
            else None,
        )
    if provider == "gemini":
        return ProviderConfig(
            name="gemini",
            model=_provider_model(settings.dspy_model, "gemini", "gemini/gemini-1.5-pro"),
            env_var="GEMINI_API_KEY",
            api_key=settings.gemini_api_key,
            configured=settings.gemini_api_key is not None,
            skipped_reason="GEMINI_API_KEY is not configured"
            if settings.gemini_api_key is None
            else None,
        )
    return ProviderConfig(
        name="openai",
        model=settings.dspy_model,
        env_var="OPENAI_API_KEY",
        api_key=settings.openai_api_key,
        configured=settings.openai_api_key is not None,
        skipped_reason="OPENAI_API_KEY is not configured"
        if settings.openai_api_key is None
        else None,
    )


def _provider_model(current_model: str, provider: str, default_model: str) -> str:
    if current_model.startswith(f"{provider}/"):
        return current_model
    if provider == "gemini" and current_model.startswith("google/"):
        return current_model
    return default_model


def _normalize_provider(provider: str | None) -> str:
    normalized = (provider or "openai").strip().lower()
    return normalized or "openai"
