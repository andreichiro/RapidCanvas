"""Small reusable helpers for Gate 6 quality, provider, and retrieval payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import isfinite
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agent.runner import AdapterMode
from app.schemas.api import ExplainRequest, ExplainResponse
from app.schemas.domain import Evidence


class EvalSupportModel(BaseModel):
    """Base model for Dev D-facing support payloads."""

    model_config = ConfigDict(extra="forbid")


class ProviderQualityMetadata(EvalSupportModel):
    """Provider metadata that is safe for reports and does not expose secrets."""

    requested_provider: str = "unknown"
    selected_provider: str = "unknown"
    provider_model: str | None = None
    provider_configured: bool | None = None
    provider_fallback_reason: str | None = None
    adapter_mode: AdapterMode = "deterministic_dev"
    adapter_notes: list[str] = Field(default_factory=list)
    latency_ms: int = Field(default=0, ge=0)
    cost_metadata: dict[str, str | bool | float | int | None] = Field(default_factory=dict)


class RetrievalQualitySignals(EvalSupportModel):
    """Retrieval-aware evidence that Dev B may enrich without changing this shape."""

    evidence_count: int = Field(ge=0)
    source_ids: list[str] = Field(default_factory=list)
    retrieval_scores: dict[str, float] = Field(default_factory=dict)
    source_diversity: int = Field(ge=0)
    sanitizer_warnings: list[str] = Field(default_factory=list)
    prompt_injection_flags: list[str] = Field(default_factory=list)
    private_url_blocks: list[str] = Field(default_factory=list)
    pending_fields: list[str] = Field(default_factory=list)


def build_provider_quality(
    response: ExplainResponse,
    request: ExplainRequest | None,
    metadata: Mapping[str, Any] | None,
) -> ProviderQualityMetadata:
    """Build provider metadata without exposing keys or provider prompts."""

    request_provider = request.provider if request else "unknown"
    requested = str(metadata_value(metadata, "requested_provider", default=request_provider))
    selected = str(metadata_value(metadata, "selected_provider", default=requested))
    fallback_reason = metadata_value(metadata, "provider_fallback_reason", default=None)
    if fallback_reason is None and response.trace.adapter_mode != "none":
        fallback_reason = first_provider_reason(
            response.trace.warnings,
            response.trace.adapter_notes,
        )
    return ProviderQualityMetadata(
        requested_provider=requested,
        selected_provider=selected,
        provider_model=string_or_none(metadata_value(metadata, "provider_model", default=None)),
        provider_configured=bool_or_none(
            metadata_value(metadata, "provider_configured", default=None)
        ),
        provider_fallback_reason=string_or_none(fallback_reason),
        adapter_mode=response.trace.adapter_mode,
        adapter_notes=list(response.trace.adapter_notes),
        latency_ms=response.trace.latency_ms,
        cost_metadata={
            "available": False,
            "skip_reason": "provider_usage_not_reported_by_current_runner",
        },
    )


def build_retrieval_quality(
    evidence: Sequence[Evidence],
    guardrail_flags: Sequence[str],
    warnings: Sequence[str],
) -> RetrievalQualitySignals:
    """Build retrieval and source-safety evidence for metrics."""

    source_ids = dedupe([item.source_id for item in evidence])
    warning_list = dedupe(warnings)
    sanitizer_warnings = [
        warning
        for warning in warning_list
        if any(marker in warning for marker in ("sanitize", "source_safety", "unsafe_source"))
    ]
    private_url_blocks = [
        warning
        for warning in warning_list
        if "private" in warning or "localhost" in warning or "127.0.0.1" in warning
    ]
    pending_fields = []
    if not sanitizer_warnings:
        pending_fields.append("sanitizer_warnings")
    if not private_url_blocks:
        pending_fields.append("private_url_blocks")
    return RetrievalQualitySignals(
        evidence_count=len(evidence),
        source_ids=source_ids,
        retrieval_scores={item.id: _finite_score(item.score) for item in evidence},
        source_diversity=len(source_ids),
        sanitizer_warnings=sanitizer_warnings,
        prompt_injection_flags=[flag for flag in guardrail_flags if "prompt_injection" in flag],
        private_url_blocks=private_url_blocks,
        pending_fields=pending_fields,
    )


def metadata_value(metadata: Mapping[str, Any] | None, key: str, *, default: Any) -> Any:
    """Read optional metadata safely."""

    if metadata is None:
        return default
    return metadata.get(key, default)


def first_provider_reason(warnings: Sequence[str], notes: Sequence[str]) -> str | None:
    """Return the first provider-related warning or adapter note."""

    for item in [*warnings, *notes]:
        if any(marker in item for marker in ("provider_", "dspy_", "DSPy provider")):
            return item
    return None


def string_or_none(value: Any) -> str | None:
    """Convert optional metadata to a string."""

    if value is None:
        return None
    return str(value)


def bool_or_none(value: Any) -> bool | None:
    """Convert optional metadata to a bool."""

    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"false", "0", "no", "off"}:
            return False
        if normalized in {"true", "1", "yes", "on"}:
            return True
    return bool(value)


def _finite_score(value: float) -> float:
    score = float(value)
    if not isfinite(score):
        return 0.0
    return round(score, 4)


def dedupe(values: Sequence[str]) -> list[str]:
    """Dedupe strings in order."""

    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped
