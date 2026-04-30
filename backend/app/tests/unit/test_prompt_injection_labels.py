from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from app.agent.program import BlueskyExplainer
from app.agent.runner import AdapterMode, ClassificationResult
from app.guardrails.output import BulletDraft, ExplanationDraft, ValidationResult
from app.schemas.domain import ContextDocument, Evidence, ImageRef, PostContext, TrustAssessment


class LabelCapturingRunner:
    adapter_mode: AdapterMode = "none"
    adapter_notes: list[str] = []

    def __init__(self) -> None:
        self.labels: list[str] = []

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
        del content
        self.labels.append(label)
        return []

    def rerank_evidence(self, post: PostContext, evidence: Sequence[Evidence]) -> list[Evidence]:
        del post
        return list(evidence)

    def assess_evidence_trust(
        self,
        post: PostContext,
        evidence: Sequence[Evidence],
    ) -> TrustAssessment:
        from app.guardrails.trust import TrustScorer

        return TrustScorer().assess(post, evidence)

    def explain(self, post: PostContext, evidence: Sequence[Evidence]) -> ExplanationDraft:
        del post
        return ExplanationDraft(
            bullets=[
                BulletDraft(text=f"Supported point {index}.", source_ids=[item.source_id])
                for index, item in enumerate(evidence, start=1)
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


def test_prompt_injection_scan_passes_source_specific_untrusted_labels() -> None:
    runner = LabelCapturingRunner()
    post = _post()
    documents = _documents(post)
    evidence = [
        Evidence(id="E1", document_id="D1", text="Thread evidence", score=0.9, source_id="S1"),
        Evidence(id="E2", document_id="D2", text="Web evidence", score=0.9, source_id="S2"),
        Evidence(id="E3", document_id="D3", text="Image evidence", score=0.9, source_id="S3"),
    ]

    BlueskyExplainer(runner=runner).explain_context(
        post=post,
        evidence=evidence,
        documents=documents,
    )

    assert "UNTRUSTED_POST_TEXT" in runner.labels
    assert "UNTRUSTED_THREAD_CONTEXT" in runner.labels
    assert "UNTRUSTED_WEB_CONTEXT" in runner.labels
    assert "UNTRUSTED_IMAGE_ALT_TEXT" in runner.labels


def _post() -> PostContext:
    return PostContext(
        url="https://bsky.app/profile/example.com/post/3abcxyz",
        at_uri="at://did:plc:example/app.bsky.feed.post/3abcxyz",
        author="example.com",
        text="Target post text",
        created_at=datetime(2026, 4, 29, tzinfo=UTC),
        parent_texts=["Parent context"],
        quoted_texts=["Quoted context"],
        images=[ImageRef(url="https://example.com/image.jpg", alt_text="Image alt")],
    )


def _documents(post: PostContext) -> list[ContextDocument]:
    return [
        ContextDocument(
            id="D1",
            source_type="thread",
            title="Thread",
            url=post.url,
            text="Thread evidence",
        ),
        ContextDocument(
            id="D2",
            source_type="web",
            title="Web",
            url="https://example.com",
            text="Web evidence",
        ),
        ContextDocument(
            id="D3",
            source_type="image",
            title="Image",
            url="https://example.com/image.jpg",
            text="Image evidence",
        ),
    ]
