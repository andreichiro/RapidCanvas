"""Final response and quality trace construction for the explainer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.agent.quality_trace import AgentQualityTrace, build_agent_quality_trace
from app.agent.response import build_guarded_response
from app.agent.runner import AdapterMode
from app.guardrails.output import ExplanationDraft, OutputGuardrail
from app.schemas.api import ExplainRequest, ExplainResponse, Source
from app.schemas.domain import (
    ContextDocument,
    Evidence,
    PostContext,
    TraceEvent,
    TrustAssessment,
)


def finalize_explanation(
    *,
    output_guardrail: OutputGuardrail,
    draft: ExplanationDraft,
    allowed_source_ids: set[str],
    post: PostContext,
    post_source_id: str,
    sources: list[Source],
    category: str,
    queries: list[str],
    warnings: Sequence[str],
    validation_issues: Sequence[str],
    trust: TrustAssessment,
    latency_ms: int,
    adapter_mode: AdapterMode,
    adapter_notes: Sequence[str],
    optimized_config: dict[str, object],
    evidence: Sequence[Evidence],
    documents: Sequence[ContextDocument],
    trace_events: Sequence[TraceEvent],
    request: ExplainRequest | None,
    provider_metadata: Mapping[str, Any],
    revision_attempted: bool,
    revision_succeeded: bool,
) -> tuple[ExplainResponse, AgentQualityTrace]:
    bullets = output_guardrail.repair(
        draft,
        allowed_source_ids,
        fallback_mode=trust.fallback_mode,
        post=post,
        post_source_id=post_source_id,
    )
    response = build_guarded_response(
        post=post,
        sources=sources,
        bullets=bullets,
        category=category,
        queries=queries,
        warnings=warnings,
        validation_issues=validation_issues,
        trust=trust,
        latency_ms=latency_ms,
        adapter_mode=adapter_mode,
        adapter_notes=adapter_notes,
        optimized_config=optimized_config,
    )
    quality = build_agent_quality_trace(
        response=response,
        evidence=evidence,
        documents=documents,
        validation_issues=validation_issues,
        revision_attempted=revision_attempted,
        revision_succeeded=revision_succeeded,
        trace_events=trace_events,
        warnings=warnings,
        request=request,
        provider_metadata=provider_metadata,
    )
    return response, quality


def finalize_explainer_run(
    program: Any,
    *,
    started: float,
    draft: ExplanationDraft,
    allowed_source_ids: set[str],
    post: PostContext,
    post_source_id: str,
    sources: list[Source],
    category: str,
    queries: list[str],
    warnings: Sequence[str],
    validation_issues: Sequence[str],
    trust: TrustAssessment,
    evidence: Sequence[Evidence],
    documents: Sequence[ContextDocument],
    request: ExplainRequest | None,
) -> tuple[ExplainResponse, AgentQualityTrace]:
    """Finalize using the explainer's private runtime state."""

    from time import perf_counter

    return finalize_explanation(
        output_guardrail=program._output_guardrail,
        draft=draft,
        allowed_source_ids=allowed_source_ids,
        post=post,
        post_source_id=post_source_id,
        sources=sources,
        category=category,
        queries=queries,
        warnings=warnings,
        validation_issues=validation_issues,
        trust=trust,
        latency_ms=int((perf_counter() - started) * 1000),
        adapter_mode=program._runner.adapter_mode,
        adapter_notes=program._runner.adapter_notes,
        optimized_config=program.optimized_config,
        evidence=evidence,
        documents=documents,
        trace_events=program.last_trace_events,
        request=request,
        provider_metadata=program.provider_metadata,
        revision_attempted=program._revision_attempted,
        revision_succeeded=program._revision_succeeded,
    )
