from __future__ import annotations

from datetime import UTC, datetime

from app.agent.judge_signatures import (
    build_judge_input_payload,
    judge_response_quality,
    judge_support_status,
)
from app.agent.program import BlueskyExplainer
from app.agent.quality_trace import build_agent_quality_trace
from app.schemas.api import Bullet, ExplainResponse, PostSummary, Source, Trace
from app.schemas.domain import ContextDocument, Evidence, PostContext


def test_judge_helper_uses_runner_without_exposing_hidden_prompts() -> None:
    program = BlueskyExplainer()
    response = program.explain_context(post=_post(), evidence=_evidence(), documents=_documents())

    payload = build_judge_input_payload(
        expected_points=["verifiable part"],
        response=response,
        evidence=_evidence(),
    )
    result = judge_response_quality(
        expected_points=["verifiable part"],
        response=response,
        evidence=_evidence(),
        runner=program._runner,  # noqa: SLF001
    )

    assert "system prompt" not in payload.model_dump_json().lower()
    assert result.status.callable is True
    assert result.status.deterministic_fallback is True
    assert 0.0 <= result.score <= 1.0


def test_judge_support_status_reports_explicit_skip_for_missing_runner_method() -> None:
    status = judge_support_status(object())

    assert status.callable is False
    assert status.skip_reason == "runner_does_not_expose_judge_evaluation_case"


def test_judge_helper_clamps_non_finite_runner_scores() -> None:
    response = BlueskyExplainer().explain_context(
        post=_post(),
        evidence=_evidence(),
        documents=_documents(),
    )

    result = judge_response_quality(
        expected_points=["verifiable part"],
        response=response,
        evidence=_evidence(),
        runner=NanJudgeRunner(),
    )

    assert result.score == 0.0
    assert result.error_labels == ["bad_score"]


def test_quality_trace_marks_unsupported_guardrail_flags_as_source_support_issues() -> None:
    post = _post()
    response = ExplainResponse(
        post=PostSummary(
            url=post.url,
            author=post.author,
            text=post.text,
            created_at=post.created_at,
        ),
        bullets=[
            Bullet(text="Supported-looking public text one.", source_ids=["S1"]),
            Bullet(text="Supported-looking public text two.", source_ids=["S1"]),
            Bullet(text="Supported-looking public text three.", source_ids=["S1"]),
        ],
        sources=[Source(id="S1", title="Source", url=post.url, type="thread", snippet=post.text)],
        trace=Trace(
            category="general_context",
            guardrail_flags=["unsupported_claim"],
            fallback_mode="partial",
        ),
    )

    trace = build_agent_quality_trace(
        response=response,
        evidence=[
            Evidence(
                id="E1",
                document_id="D1",
                text="Source text",
                score=0.9,
                source_id="S1",
            )
        ],
        documents=[],
        validation_issues=[],
        revision_attempted=False,
        revision_succeeded=False,
        trace_events=[],
        warnings=[],
    )

    assert trace.guardrails.unsupported_claim_indicators == ["unsupported_claim"]
    assert trace.guardrails.source_support_validation_status == "partial"
    assert trace.guardrails.source_support_issues == ["unsupported_claim"]


class NanJudgeRunner:
    adapter_mode = "none"

    def judge_evaluation_case(self, expected, prediction, evidence):  # type: ignore[no-untyped-def]
        del expected, prediction, evidence
        return {"score": "nan", "error_labels": ["bad_score"]}


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
            text=f"Detailed explanation source {index}.",
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
