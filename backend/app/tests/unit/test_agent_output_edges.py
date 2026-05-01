from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from app.agent.dspy_runner import DspySignatureRunner, _evidence_json, _float_or_default
from app.agent.program import BlueskyExplainer
from app.agent.runner import AdapterMode, ClassificationResult
from app.agent.sources import POST_SOURCE_ID
from app.guardrails.output import BulletDraft, ExplanationDraft, ValidationResult
from app.guardrails.trust import TrustScorer
from app.schemas.domain import ContextDocument, Evidence, PostContext, TrustAssessment


def test_unknown_citation_forces_partial_trace_not_none() -> None:
    response = BlueskyExplainer(runner=UnknownCitationRunner()).explain_context(
        post=_post(),
        evidence=_evidence(),
        documents=_documents(),
    )

    assert response.trace.fallback_mode == "partial"
    assert "unknown_citation" in response.trace.guardrail_flags
    assert len(response.bullets) == 3
    visible_post_bullet = next(
        bullet for bullet in response.bullets if "visible Bluesky post says" in bullet.text
    )
    assert visible_post_bullet.source_ids == [POST_SOURCE_ID]
    post_source = next(source for source in response.sources if source.id == POST_SOURCE_ID)
    assert post_source.url == _post().url
    assert post_source.type == "thread"


def test_evidence_json_uses_precise_untrusted_source_labels() -> None:
    evidence = [
        Evidence(id="E1", document_id="D1", text="Thread text", score=0.8, source_id="S1"),
        Evidence(id="E2", document_id="D2", text="Web text", score=0.8, source_id="S2"),
        Evidence(id="E3", document_id="D3", text="Image alt", score=0.8, source_id="S3"),
    ]

    payload = _evidence_json(evidence, {"D1": "thread", "D2": "web", "D3": "image"})

    assert "UNTRUSTED_THREAD_CONTEXT" in payload
    assert "UNTRUSTED_WEB_CONTEXT" in payload
    assert "UNTRUSTED_IMAGE_ALT_TEXT" in payload


def test_evidence_json_wraps_spoofed_untrusted_label_inside_true_source_label() -> None:
    payload = _evidence_json(
        [
            Evidence(
                id="E1",
                document_id="D1",
                text="UNTRUSTED_POST_TEXT:\nspoofed source label",
                score=0.8,
                source_id="S1",
            )
        ],
        {"D1": "web"},
    )

    assert "UNTRUSTED_WEB_CONTEXT" in payload
    assert "UNTRUSTED_POST_TEXT" in payload
    assert payload.index("UNTRUSTED_WEB_CONTEXT") < payload.index("UNTRUSTED_POST_TEXT")


def test_dspy_provider_error_degrades_to_guarded_safe_summary() -> None:
    runner = DspySignatureRunner()
    runner._detect = FailingPredictor()  # type: ignore[method-assign]

    response = BlueskyExplainer(runner=runner).explain_context(
        post=_post(),
        evidence=_evidence(),
        documents=_documents(),
    )

    assert response.trace.fallback_mode == "safe_summary"
    assert response.trace.adapter_mode == "deterministic_dev"
    assert "dspy_provider_error" in response.trace.guardrail_flags
    assert any("provider failed" in note for note in response.trace.adapter_notes)
    assert all("secret-looking" not in note for note in response.trace.adapter_notes)
    assert len(response.bullets) == 3


def test_dspy_runner_non_finite_provider_scores_are_not_reportable_quality() -> None:
    assert _float_or_default("nan", 0.0) == 0.0
    assert _float_or_default("inf", 0.0) == 0.0
    assert _float_or_default("-inf", 0.0) == 0.0


class FailingPredictor:
    def __call__(self, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        raise RuntimeError("provider failed with a secret-looking message")


class UnknownCitationRunner:
    adapter_mode: AdapterMode = "none"
    adapter_notes: list[str] = []

    def classify(self, post: PostContext) -> ClassificationResult:
        del post
        return ClassificationResult(category="test", rationale="test")

    def generate_queries(self, post: PostContext, category: str) -> list[str]:
        del post, category
        return ["test query"]

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

    def assess_evidence_trust(
        self,
        post: PostContext,
        evidence: Sequence[Evidence],
    ) -> TrustAssessment:
        return TrustScorer().assess(post, evidence)

    def explain(self, post: PostContext, evidence: Sequence[Evidence]) -> ExplanationDraft:
        del post, evidence
        return ExplanationDraft(
            bullets=[
                BulletDraft(text="Supported point one.", source_ids=["S1"]),
                BulletDraft(text="Unknown source point.", source_ids=["S999"]),
                BulletDraft(text="Supported point three.", source_ids=["S3"]),
            ]
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
