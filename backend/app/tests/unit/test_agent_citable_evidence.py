from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from app.agent.program import BlueskyExplainer
from app.agent.runner import AdapterMode, ClassificationResult
from app.guardrails.output import BulletDraft, ExplanationDraft, ValidationResult
from app.guardrails.trust import TrustScorer
from app.schemas.domain import ContextDocument, Evidence, PostContext, TrustAssessment


def _post() -> PostContext:
    return PostContext(
        url="https://bsky.app/profile/example.com/post/3abcxyz",
        at_uri="at://did:plc:example/app.bsky.feed.post/3abcxyz",
        author="example.com",
        text="Why is this old quote suddenly everywhere?",
        created_at=datetime(2026, 4, 29, tzinfo=UTC),
    )


class CapturingCitableEvidenceRunner:
    adapter_mode: AdapterMode = "none"
    adapter_notes: list[str] = []

    def __init__(self) -> None:
        self.explain_source_ids: list[str] = []
        self.trust_source_ids: list[str] = []

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
        self.trust_source_ids = [item.source_id for item in evidence]
        return TrustScorer().assess(post, evidence)

    def explain(self, post: PostContext, evidence: Sequence[Evidence]) -> ExplanationDraft:
        del post
        self.explain_source_ids = [item.source_id for item in evidence]
        return ExplanationDraft(
            bullets=[
                BulletDraft(
                    text=f"{item.text} explains a verified part.",
                    source_ids=[item.source_id],
                )
                for item in evidence[:3]
            ]
        )

    def judge_evaluation_case(
        self,
        expected: str,
        prediction: str,
        evidence: Sequence[Evidence],
    ) -> dict[str, float | list[str]]:
        del expected, prediction, evidence
        return {"score": 1.0, "error_labels": []}

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


def test_explainer_filters_non_eligible_diagnostic_evidence_before_generation() -> None:
    runner = CapturingCitableEvidenceRunner()
    documents = [_good_document(index) for index in range(1, 4)]
    documents.append(_bad_document())
    evidence = [_good_evidence(index) for index in range(1, 4)]
    evidence.append(
        Evidence(
            id="E4",
            document_id="BAD",
            text="Unrelated trading card catalog marketplace.",
            score=0.99,
            source_id="BAD",
        )
    )

    response = BlueskyExplainer(runner=runner).explain_context(
        post=_post(),
        evidence=evidence,
        documents=documents,
    )

    assert runner.explain_source_ids == ["GOOD1", "GOOD2", "GOOD3"]
    assert runner.trust_source_ids == ["GOOD1", "GOOD2", "GOOD3"]
    assert "BAD" not in {source.id for source in response.sources}
    assert "ineligible_citation" not in response.trace.guardrail_flags


def _good_document(index: int) -> ContextDocument:
    return ContextDocument(
        id=f"GOOD{index}",
        source_type="web",
        title=f"Good source {index}",
        url=f"https://example.com/good-{index}",
        text=f"Good source {index} explains a verified part.",
        metadata={"citation_eligible": True, "source_quality_score": 0.92},
    )


def _bad_document() -> ContextDocument:
    return ContextDocument(
        id="BAD",
        source_type="web",
        title="Trading card catalog",
        url="https://tcdb.com/card",
        text="Unrelated trading card catalog marketplace.",
        metadata={
            "citation_eligible": False,
            "source_quality_score": 0.12,
            "source_quality_reasons": ["commercial_catalog_domain"],
        },
    )


def _good_evidence(index: int) -> Evidence:
    return Evidence(
        id=f"E{index}",
        document_id=f"GOOD{index}",
        text=f"Good source {index} explains a verified part.",
        score=0.92,
        source_id=f"GOOD{index}",
    )
