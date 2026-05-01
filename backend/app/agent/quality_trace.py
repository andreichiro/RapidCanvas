"""Structured Gate 6 quality evidence for agent and guardrail evaluation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent.eval_support import (
    ProviderQualityMetadata,
    RetrievalQualitySignals,
    build_provider_quality,
    build_retrieval_quality,
    dedupe,
)
from app.guardrails.policies import compact_text
from app.schemas.api import ExplainRequest, ExplainResponse
from app.schemas.domain import (
    ContextDocument,
    Evidence,
    FallbackMode,
    TraceEvent,
)

SourceSupportStatus = Literal["supported", "partial", "unsupported", "unknown"]

_UNSUPPORTED_ISSUES = {
    "uncited_output",
    "unknown_citation",
    "unsupported_claim",
    "unsupported_factual_claim",
}
_UNSAFE_ISSUES = {
    "leaked_instruction_or_secret",
    "unsafe_output",
    "source_quote_leakage",
}
_SOURCE_SUPPORT_ISSUES = {
    "uncited_output",
    "unknown_citation",
    "invalid_output_shape",
}


class QualityModel(BaseModel):
    """Base model for Dev D-consumable internal quality payloads."""

    model_config = ConfigDict(extra="forbid")


class BulletEvidenceUse(QualityModel):
    """Evidence and source ids used by a public bullet."""

    bullet_index: int = Field(ge=0)
    text: str
    source_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    missing_source_ids: list[str] = Field(default_factory=list)
    source_support_status: SourceSupportStatus = "unknown"


class QueryPlanQuality(QualityModel):
    """Safe query-plan summary without hidden prompts or chain-of-thought."""

    category: str
    queries: list[str] = Field(default_factory=list)
    query_count: int = Field(ge=0)


class GuardrailQualityOutput(QualityModel):
    """Guardrail and fallback evidence exposed for Gate 6 scoring."""

    fallback_mode: FallbackMode
    fallback_reasons: list[str] = Field(default_factory=list)
    abstention_reasons: list[str] = Field(default_factory=list)
    unsupported_claim_indicators: list[str] = Field(default_factory=list)
    prompt_injection_resistance_signals: list[str] = Field(default_factory=list)
    source_support_validation_status: SourceSupportStatus = "unknown"
    source_support_issues: list[str] = Field(default_factory=list)
    unsafe_output_flags: list[str] = Field(default_factory=list)
    validation_issues: list[str] = Field(default_factory=list)
    revision_attempted: bool = False
    revision_succeeded: bool = False
    guardrail_flags: list[str] = Field(default_factory=list)


class AgentQualityTrace(QualityModel):
    """One structured quality snapshot for a completed agent run."""

    schema_version: int = 1
    category: str
    query_plan_summary: QueryPlanQuality
    bullet_evidence: list[BulletEvidenceUse] = Field(default_factory=list)
    validation_issues: list[str] = Field(default_factory=list)
    guardrails: GuardrailQualityOutput
    provider: ProviderQualityMetadata
    retrieval: RetrievalQualitySignals
    trace_events: list[TraceEvent] = Field(default_factory=list)
    chain_of_thought_exposed: bool = False
    hidden_prompts_exposed: bool = False


def build_agent_quality_trace(
    *,
    response: ExplainResponse,
    evidence: Sequence[Evidence],
    documents: Sequence[ContextDocument],
    validation_issues: Sequence[str],
    revision_attempted: bool,
    revision_succeeded: bool,
    trace_events: Sequence[TraceEvent],
    warnings: Sequence[str],
    request: ExplainRequest | None = None,
    provider_metadata: Mapping[str, Any] | None = None,
) -> AgentQualityTrace:
    """Build a serializable Gate 6 quality trace without chain-of-thought."""

    del documents
    provider = build_provider_quality(response, request, provider_metadata)
    guardrails = _guardrail_quality(
        response=response,
        validation_issues=validation_issues,
        revision_attempted=revision_attempted,
        revision_succeeded=revision_succeeded,
    )
    return AgentQualityTrace(
        category=response.trace.category,
        query_plan_summary=QueryPlanQuality(
            category=response.trace.category,
            queries=list(response.trace.queries),
            query_count=len(response.trace.queries),
        ),
        bullet_evidence=_bullet_evidence(response, evidence),
        validation_issues=dedupe(validation_issues),
        guardrails=guardrails,
        provider=provider,
        retrieval=build_retrieval_quality(evidence, response.trace.guardrail_flags, warnings),
        trace_events=list(trace_events),
    )


def quality_trace_payload(trace: AgentQualityTrace) -> dict[str, Any]:
    """Return a JSON-stable dict payload for Dev D fixtures and reports."""

    return trace.model_dump(mode="json")


def _bullet_evidence(
    response: ExplainResponse,
    evidence: Sequence[Evidence],
) -> list[BulletEvidenceUse]:
    evidence_by_source: dict[str, list[str]] = {}
    for item in evidence:
        evidence_by_source.setdefault(item.source_id, []).append(item.id)
    known_sources = {source.id for source in response.sources}
    bullets: list[BulletEvidenceUse] = []
    for index, bullet in enumerate(response.bullets):
        missing = [source_id for source_id in bullet.source_ids if source_id not in known_sources]
        evidence_ids = [
            evidence_id
            for source_id in bullet.source_ids
            for evidence_id in evidence_by_source.get(source_id, [])
        ]
        bullets.append(
            BulletEvidenceUse(
                bullet_index=index,
                text=compact_text(bullet.text, limit=420),
                source_ids=list(bullet.source_ids),
                evidence_ids=dedupe(evidence_ids),
                missing_source_ids=missing,
                source_support_status=_bullet_support_status(bullet.source_ids, missing),
            )
        )
    return bullets


def _bullet_support_status(
    source_ids: Sequence[str],
    missing: Sequence[str],
) -> SourceSupportStatus:
    if missing:
        return "unsupported"
    if source_ids:
        return "supported"
    return "unsupported"


def _guardrail_quality(
    *,
    response: ExplainResponse,
    validation_issues: Sequence[str],
    revision_attempted: bool,
    revision_succeeded: bool,
) -> GuardrailQualityOutput:
    issues = dedupe(validation_issues)
    flags = dedupe(response.trace.guardrail_flags)
    reasons = dedupe(response.trace.warnings)
    unsupported = dedupe([item for item in [*issues, *flags] if item in _UNSUPPORTED_ISSUES])
    unsafe = dedupe([item for item in [*issues, *flags] if item in _UNSAFE_ISSUES])
    source_issues = dedupe(
        [
            item
            for item in [*issues, *flags]
            if item in _SOURCE_SUPPORT_ISSUES or item in _UNSUPPORTED_ISSUES
        ]
    )
    return GuardrailQualityOutput(
        fallback_mode=response.trace.fallback_mode,
        fallback_reasons=reasons if response.trace.fallback_mode != "none" else [],
        abstention_reasons=reasons if response.trace.fallback_mode == "abstain" else [],
        unsupported_claim_indicators=unsupported,
        prompt_injection_resistance_signals=[
            item for item in [*flags, *reasons] if "prompt_injection" in item
        ],
        source_support_validation_status=_source_support_status(
            response.trace.fallback_mode,
            source_issues,
            response.bullets,
        ),
        source_support_issues=source_issues,
        unsafe_output_flags=unsafe,
        validation_issues=issues,
        revision_attempted=revision_attempted,
        revision_succeeded=revision_succeeded,
        guardrail_flags=flags,
    )


def _source_support_status(
    fallback_mode: FallbackMode,
    source_issues: Sequence[str],
    bullets: Sequence[Any],
) -> SourceSupportStatus:
    if source_issues:
        return "partial" if fallback_mode in {"partial", "safe_summary"} else "unsupported"
    if all(getattr(bullet, "source_ids", None) for bullet in bullets):
        return "supported"
    return "unknown"
