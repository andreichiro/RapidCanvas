from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter

from app.agent.finalize import FinalizationContext, finalize_explainer_run
from app.guardrails.output import BulletDraft, ExplanationDraft, OutputGuardrail
from app.schemas.api import Source
from app.schemas.domain import ContextDocument, Evidence, PostContext, TraceEvent, TrustAssessment


def _post() -> PostContext:
    return PostContext(
        url="https://bsky.app/profile/example.com/post/3abcxyz",
        at_uri="at://did:plc:example/app.bsky.feed.post/3abcxyz",
        author="example.com",
        text="Why is this old quote suddenly everywhere?",
        created_at=datetime(2026, 4, 29, tzinfo=UTC),
    )


def _documents() -> list[ContextDocument]:
    return [
        ContextDocument(
            id=f"D{index}",
            source_type="web",
            title=f"Context source {index}",
            url=f"https://example.com/source-{index}",
            text=f"Evidence {index} explains one verifiable part of the post.",
        )
        for index in range(1, 4)
    ]


def _evidence() -> list[Evidence]:
    return [
        Evidence(
            id=f"E{index}",
            document_id=f"D{index}",
            text=f"Evidence {index} explains one verifiable part of the post.",
            score=0.9,
            source_id=f"S{index}",
        )
        for index in range(1, 4)
    ]


class ContextOnlyProgram:
    def finalization_context(self) -> FinalizationContext:
        return FinalizationContext(
            output_guardrail=OutputGuardrail(),
            adapter_mode="none",
            adapter_notes=("provider-backed synthesis completed",),
            optimized_config={"schema_version": 1},
            trace_events=(TraceEvent(step="finalize", status="completed"),),
            provider_metadata={"provider": "openai"},
            revision_attempted=True,
            revision_succeeded=False,
        )


def test_finalizer_accepts_context_only_program_without_explainer_internals() -> None:
    sources = [
        Source(
            id=f"S{index}",
            title=f"Source {index}",
            url=f"https://example.com/source-{index}",
            type="web",
            snippet=f"Evidence {index} explains one verifiable part of the post.",
        )
        for index in range(1, 4)
    ]
    draft = ExplanationDraft(
        bullets=[
            BulletDraft(
                text=f"Evidence {index} explains one verifiable part of the post.",
                source_ids=[f"S{index}"],
            )
            for index in range(1, 4)
        ]
    )

    response, quality = finalize_explainer_run(
        ContextOnlyProgram(),
        started=perf_counter(),
        draft=draft,
        allowed_source_ids={source.id for source in sources},
        post=_post(),
        post_source_id=sources[0].id,
        sources=sources,
        category="context",
        queries=["context query"],
        warnings=[],
        validation_issues=[],
        trust=TrustAssessment(score=0.95, fallback_mode="none", flags=[], reasons=[]),
        evidence=_evidence(),
        documents=_documents(),
        request=None,
    )

    assert response.trace.adapter_mode == "none"
    assert response.trace.provider == "openai"
    assert response.trace.adapter_notes == ["provider-backed synthesis completed"]
    assert response.trace.warnings == ["optimized_program_loaded"]
    assert quality.guardrails.revision_attempted is True
    assert quality.guardrails.revision_succeeded is False
