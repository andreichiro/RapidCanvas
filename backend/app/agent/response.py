"""Response construction helpers for the runtime explainer."""

from __future__ import annotations

from collections.abc import Sequence

from app.agent.runner import AdapterMode
from app.schemas.api import Bullet, ExplainResponse, PostSummary, Source, Trace
from app.schemas.domain import PostContext, TrustAssessment


def build_explain_response(
    *,
    post: PostContext,
    sources: list[Source],
    bullets: list[Bullet],
    category: str,
    queries: list[str],
    trace_warnings: list[str],
    guardrail_flags: list[str],
    trust: TrustAssessment,
    latency_ms: int,
    adapter_mode: AdapterMode,
    adapter_notes: Sequence[str],
) -> ExplainResponse:
    """Build the public schema object from validated internals."""

    return ExplainResponse(
        post=PostSummary(
            url=post.url,
            author=post.author,
            text=post.text,
            created_at=post.created_at,
        ),
        bullets=bullets,
        sources=sources,
        trace=Trace(
            category=category,
            queries=queries,
            warnings=trace_warnings,
            latency_ms=latency_ms,
            trust_score=trust.score,
            fallback_mode=trust.fallback_mode,
            guardrail_flags=dedupe(guardrail_flags),
            adapter_mode=adapter_mode,
            adapter_notes=list(adapter_notes),
        ),
    )


def build_guarded_response(
    *,
    post: PostContext,
    bullets: list[Bullet],
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
) -> ExplainResponse:
    """Build the response emitted by the guarded explainer workflow."""

    optimized = ["optimized_program_loaded"] if optimized_config.get("schema_version") else []
    trace_warnings = dedupe([*warnings, *trust.reasons, *validation_issues, *optimized])
    return build_explain_response(
        post=post,
        bullets=bullets,
        sources=sources,
        category=category,
        queries=queries,
        trace_warnings=trace_warnings,
        guardrail_flags=dedupe([*trust.flags, *validation_issues]),
        trust=trust,
        latency_ms=latency_ms,
        adapter_mode=adapter_mode,
        adapter_notes=adapter_notes,
    )


def dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped
