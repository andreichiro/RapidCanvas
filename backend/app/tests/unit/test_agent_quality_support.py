from __future__ import annotations

from datetime import UTC, datetime

from app.agent.judge_signatures import (
    build_judge_input_payload,
    judge_response_quality,
    judge_support_status,
)
from app.agent.program import BlueskyExplainer
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
