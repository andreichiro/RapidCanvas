from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from app.agent.program import BlueskyExplainer
from app.agent.runner import AdapterMode, ClassificationResult
from app.agent.sources import POST_SOURCE_ID
from app.guardrails.output import BulletDraft, ExplanationDraft, ValidationResult
from app.schemas.domain import Evidence, PostContext, TrustAssessment


def test_sparse_fallback_is_useful_source_backed_and_does_not_crash() -> None:
    response = BlueskyExplainer().explain_context(post=_post("rose"), evidence=[], documents=[])

    assert response.trace.fallback_mode in {"partial", "safe_summary"}
    assert len(response.bullets) == 3
    assert all(bullet.source_ids == [POST_SOURCE_ID] for bullet in response.bullets)
    rendered = " ".join(bullet.text.lower() for bullet in response.bullets)
    assert "sparse context" in rendered
    assert "safe summary" in rendered
    assert "no broader claim" in rendered


def test_link_fallback_returns_schema_valid_bullets_when_draft_is_unsupported() -> None:
    response = BlueskyExplainer(runner=UnsupportedLinkRunner()).explain_context(
        post=_post("Bluesky links to David Imel's ATmosphereConf summary."),
        evidence=[],
        documents=[],
    )

    assert response.trace.fallback_mode in {"partial", "safe_summary"}
    assert len(response.bullets) == 3
    assert all(bullet.source_ids == [POST_SOURCE_ID] for bullet in response.bullets)
    assert "Generated fallback bullets failed" not in " ".join(response.trace.warnings)


class UnsupportedLinkRunner:
    adapter_mode: AdapterMode = "none"
    adapter_notes: list[str] = []

    def classify(self, post: PostContext) -> ClassificationResult:
        del post
        return ClassificationResult(category="link_context", rationale="test")

    def generate_queries(self, post: PostContext, category: str) -> list[str]:
        del post, category
        return ["ATmosphereConf"]

    def detect_prompt_injection(
        self,
        content: str,
        label: str = "UNTRUSTED_WEB_CONTEXT",
    ) -> list[str]:
        del content, label
        return []

    def rerank_evidence(self, post: PostContext, evidence: Sequence[Evidence]) -> list[Evidence]:
        del post
        return list(evidence)

    def explain(self, post: PostContext, evidence: Sequence[Evidence]) -> ExplanationDraft:
        del post, evidence
        return ExplanationDraft(
            bullets=[
                BulletDraft(
                    text="The article announced a detailed conference outcome in 2026.",
                    source_ids=[],
                )
            ]
        )

    def assess_evidence_trust(
        self,
        post: PostContext,
        evidence: Sequence[Evidence],
    ) -> TrustAssessment:
        del post, evidence
        return TrustAssessment(
            score=0.2,
            fallback_mode="partial",
            flags=["low_evidence"],
            reasons=["Fewer than three evidence chunks were available."],
        )

    def validate(
        self,
        post: PostContext,
        draft: ExplanationDraft,
        evidence: Sequence[Evidence],
    ) -> ValidationResult:
        del post, evidence
        return ValidationResult(is_valid=True, revised_bullets=draft.bullets)

    def revise(
        self,
        post: PostContext,
        draft: ExplanationDraft,
        evidence: Sequence[Evidence],
        issues: Sequence[str],
    ) -> ExplanationDraft:
        del post, evidence, issues
        return draft

    def judge_evaluation_case(
        self,
        expected: str,
        prediction: str,
        evidence: Sequence[Evidence],
    ) -> dict[str, float | list[str]]:
        del expected, prediction, evidence
        return {"score": 1.0, "error_labels": []}


def _post(text: str) -> PostContext:
    return PostContext(
        url="https://bsky.app/profile/example.com/post/3abcxyz",
        at_uri="at://did:plc:example/app.bsky.feed.post/3abcxyz",
        author="example.com",
        text=text,
        created_at=datetime(2026, 4, 29, tzinfo=UTC),
    )
