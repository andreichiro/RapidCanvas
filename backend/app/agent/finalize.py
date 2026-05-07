"""Final response and quality trace construction for the explainer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from app.agent.evidence_contract import snippet_only_source_ids, source_text_by_id
from app.agent.quality_trace import AgentQualityTrace, build_agent_quality_trace
from app.agent.response import build_guarded_response
from app.agent.runner import AdapterMode
from app.guardrails.output import ExplanationDraft, OutputGuardrail
from app.schemas.api import Bullet, ExplainRequest, ExplainResponse, Source
from app.schemas.domain import (
    ContextDocument,
    Evidence,
    PostContext,
    TraceEvent,
    TrustAssessment,
)


@dataclass(frozen=True)
class FinalizationContext:
    """Public runtime state needed to finalize an explainer response."""

    output_guardrail: OutputGuardrail
    adapter_mode: AdapterMode
    adapter_notes: tuple[str, ...]
    optimized_config: dict[str, Any]
    trace_events: tuple[TraceEvent, ...]
    provider_metadata: Mapping[str, Any]
    revision_attempted: bool
    revision_succeeded: bool


class SupportsFinalizationContext(Protocol):
    """Object that can expose finalization state without private attribute reads."""

    def finalization_context(self) -> FinalizationContext:
        """Return the public finalization context for the current run."""


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
    bullets = _repair_bullets(
        output_guardrail, draft, allowed_source_ids, trust, post,
        post_source_id, evidence, documents,
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
    _apply_trace_enrichment(response, request, provider_metadata, documents)
    quality = _quality_trace(
        response, evidence, documents, validation_issues, revision_attempted,
        revision_succeeded, trace_events, warnings, request, provider_metadata,
    )
    return response, quality


def _quality_trace(
    response: ExplainResponse,
    evidence: Sequence[Evidence],
    documents: Sequence[ContextDocument],
    validation_issues: Sequence[str],
    revision_attempted: bool,
    revision_succeeded: bool,
    trace_events: Sequence[TraceEvent],
    warnings: Sequence[str],
    request: ExplainRequest | None,
    provider_metadata: Mapping[str, Any],
) -> AgentQualityTrace:
    return build_agent_quality_trace(
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


def _repair_bullets(
    output_guardrail: OutputGuardrail,
    draft: ExplanationDraft,
    allowed_source_ids: set[str],
    trust: TrustAssessment,
    post: PostContext,
    post_source_id: str,
    evidence: Sequence[Evidence],
    documents: Sequence[ContextDocument],
) -> list[Bullet]:
    return output_guardrail.repair(
        draft,
        allowed_source_ids,
        fallback_mode=trust.fallback_mode,
        post=post,
        post_source_id=post_source_id,
        source_text_by_id=source_text_by_id(evidence),
        snippet_only_source_ids=snippet_only_source_ids(documents, evidence),
    )


def _apply_trace_enrichment(
    response: ExplainResponse,
    request: ExplainRequest | None,
    provider_metadata: Mapping[str, Any],
    documents: Sequence[ContextDocument],
) -> None:
    response.trace.provider = _provider_name(request, provider_metadata)
    response.trace.vector_store_backend = _vector_store_backend(response.trace.warnings)
    response.trace.source_quality = _source_quality_trace(documents)
    response.trace.image_status = _image_status_trace(documents)


def _provider_name(
    request: ExplainRequest | None,
    provider_metadata: Mapping[str, Any],
) -> str | None:
    provider = provider_metadata.get("provider") or provider_metadata.get("name")
    if isinstance(provider, str) and provider:
        return provider
    if request is not None:
        return request.provider
    return None


def _vector_store_backend(warnings: Sequence[str]) -> str | None:
    for warning in warnings:
        if warning in {"qdrant_vector_store", "in_memory_fallback"}:
            return warning
    for warning in warnings:
        if "qdrant_vector_store" in warning:
            return "qdrant_vector_store"
        if "in_memory_fallback" in warning:
            return "in_memory_fallback"
    return None


def _source_quality_trace(documents: Sequence[ContextDocument]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for document in documents:
        metadata = document.metadata
        if "source_quality_score" not in metadata:
            continue
        rows.append(
            {
                "id": document.id,
                "title": document.title,
                "url": document.url,
                "source_type": document.source_type,
                "quality_score": metadata.get("source_quality_score"),
                "quality_reasons": metadata.get("source_quality_reasons", []),
                "citation_eligible": metadata.get("citation_eligible"),
            }
        )
    return rows


def _image_status_trace(documents: Sequence[ContextDocument]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for document in documents:
        if document.source_type != "image":
            continue
        metadata = document.metadata
        rows.append(
            {
                "id": document.id,
                "url": document.url,
                "vision_model": metadata.get("vision_model"),
                "vision_used": metadata.get("vision_used"),
                "alt_text_used": metadata.get("alt_text_used"),
                "image_evidence_role": metadata.get("image_evidence_role") or metadata.get("role"),
                "image_index": metadata.get("image_index"),
                "vision_warning": metadata.get("vision_warning"),
                "prompt_injection_flags": metadata.get("prompt_injection_flags", []),
            }
        )
    return rows


def finalize_explainer_run(
    program: SupportsFinalizationContext,
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
    """Finalize using the explainer's public runtime context."""

    from time import perf_counter

    context = program.finalization_context()
    return finalize_explanation(
        output_guardrail=context.output_guardrail,
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
        adapter_mode=context.adapter_mode,
        adapter_notes=context.adapter_notes,
        optimized_config=context.optimized_config,
        evidence=evidence,
        documents=documents,
        trace_events=context.trace_events,
        request=request,
        provider_metadata=context.provider_metadata,
        revision_attempted=context.revision_attempted,
        revision_succeeded=context.revision_succeeded,
    )
