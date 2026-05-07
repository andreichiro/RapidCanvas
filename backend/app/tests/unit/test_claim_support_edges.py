from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from types import SimpleNamespace

from app.agent.dspy_runner import DspySignatureRunner
from app.agent.program import BlueskyExplainer
from app.agent.runner import AdapterMode, ClassificationResult
from app.guardrails.output import BulletDraft, ExplanationDraft, ValidationResult
from app.guardrails.trust import TrustScorer
from app.schemas.domain import ContextDocument, Evidence, PostContext, TrustAssessment


def test_dspy_validation_labels_are_normalized_to_explicit_contract() -> None:
    runner = DspySignatureRunner()
    runner._validate = _ValidationLabelPredictor()  # type: ignore[method-assign]

    result = runner.validate(_post(), ExplanationDraft(bullets=[]), _evidence())

    assert result.issues == [
        "unsupported_claim",
        "weak_citation_support",
        "off_topic_citation",
        "needs_primary_source",
        "unsafe_echo",
        "non_english_output",
    ]


def test_revision_cannot_use_snippet_only_source_for_broad_claim() -> None:
    response = BlueskyExplainer(runner=_SnippetOnlyRevisionRunner()).explain_context(
        post=_post(),
        evidence=_snippet_evidence(),
        documents=_snippet_documents(),
    )

    serialized = " ".join(bullet.text for bullet in response.bullets)
    assert "The policy passed because the committee confirmed the final vote." not in serialized
    assert response.trace.fallback_mode == "partial"
    assert "needs_primary_source" in response.trace.guardrail_flags
    assert all(bullet.source_ids for bullet in response.bullets)


def test_unrelated_primary_citation_cannot_mask_snippet_only_claim_support() -> None:
    response = BlueskyExplainer(runner=_MixedSnippetPrimaryRunner()).explain_context(
        post=_post(),
        evidence=_mixed_snippet_evidence(),
        documents=_mixed_snippet_documents(),
    )

    serialized = " ".join(bullet.text for bullet in response.bullets)
    assert "The policy passed because the committee confirmed the final vote." not in serialized
    assert response.trace.fallback_mode == "partial"
    assert "needs_primary_source" in response.trace.guardrail_flags


class _ValidationLabelPredictor:
    def __call__(self, **kwargs: object) -> SimpleNamespace:
        del kwargs
        return SimpleNamespace(
            is_valid="false",
            issues_json=(
                '["unsupported claim", "weak-citation", "off topic source", '
                '"snippet only", "leaked_instruction_or_secret", "not-a-real-label", '
                '"non english"]'
            ),
            revised_bullets_json="[]",
        )


class _SnippetOnlyRevisionRunner:
    adapter_mode: AdapterMode = "none"
    adapter_notes: list[str] = []

    def classify(self, post: PostContext) -> ClassificationResult:
        del post
        return ClassificationResult(category="test", rationale="test")

    def generate_queries(self, post: PostContext, category: str) -> list[str]:
        del post, category
        return []

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
        return ExplanationDraft(bullets=[])

    def validate(
        self,
        post: PostContext,
        draft: ExplanationDraft,
        evidence: Sequence[Evidence],
    ) -> ValidationResult:
        del post, draft, evidence
        return ValidationResult(is_valid=False, issues=["non_english_output"])

    def revise(
        self,
        post: PostContext,
        draft: ExplanationDraft,
        evidence: Sequence[Evidence],
        issues: Sequence[str],
    ) -> ExplanationDraft:
        del post, draft, evidence, issues
        return ExplanationDraft(
            bullets=[
                BulletDraft(
                    text="The policy passed because the committee confirmed the final vote.",
                    source_ids=["S-snippet"],
                ),
                BulletDraft(
                    text="The policy passed because the committee confirmed the final vote.",
                    source_ids=["S-snippet"],
                ),
                BulletDraft(
                    text="The policy passed because the committee confirmed the final vote.",
                    source_ids=["S-snippet"],
                ),
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


class _MixedSnippetPrimaryRunner(_SnippetOnlyRevisionRunner):
    def explain(self, post: PostContext, evidence: Sequence[Evidence]) -> ExplanationDraft:
        del post, evidence
        return ExplanationDraft(
            bullets=[
                BulletDraft(
                    text="The policy passed because the committee confirmed the final vote.",
                    source_ids=["S-snippet", "S-primary"],
                ),
                BulletDraft(
                    text="The policy passed because the committee confirmed the final vote.",
                    source_ids=["S-snippet", "S-primary"],
                ),
                BulletDraft(
                    text="The policy passed because the committee confirmed the final vote.",
                    source_ids=["S-snippet", "S-primary"],
                ),
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


def _post() -> PostContext:
    return PostContext(
        url="https://bsky.app/profile/example.com/post/3claimedge",
        at_uri="at://did:plc:example/app.bsky.feed.post/3claimedge",
        author="example.com",
        text="What happened with this policy?",
        created_at=datetime(2026, 5, 5, tzinfo=UTC),
    )


def _evidence() -> list[Evidence]:
    return [Evidence(id="E1", document_id="D1", text="Evidence text.", score=0.9, source_id="S1")]


def _snippet_evidence() -> list[Evidence]:
    return [
        Evidence(
            id="E1",
            document_id="D-snippet",
            text="The policy passed because the committee confirmed the final vote.",
            score=0.9,
            source_id="S-snippet",
        ),
        Evidence(
            id="E2", document_id="D-primary", text="Primary source.", score=0.9, source_id="S2"
        ),
        Evidence(
            id="E3", document_id="D-primary", text="Primary source.", score=0.9, source_id="S2"
        ),
    ]


def _snippet_documents() -> list[ContextDocument]:
    return [
        ContextDocument(
            id="D-snippet",
            source_type="web",
            title="Snippet source",
            url="https://example.test/snippet",
            text="The policy passed because the committee confirmed the final vote.",
            metadata={"snippet_only": True},
        ),
        ContextDocument(
            id="D-primary",
            source_type="web",
            title="Primary source",
            url="https://example.test/primary",
            text="Primary source.",
            metadata={"citation_eligible": True},
        ),
    ]


def _mixed_snippet_evidence() -> list[Evidence]:
    return [
        Evidence(
            id="E1",
            document_id="D-snippet",
            text="The policy passed because the committee confirmed the final vote.",
            score=0.95,
            source_id="S-snippet",
        ),
        Evidence(
            id="E2",
            document_id="D-primary",
            text="Primary source lists committee membership and meeting calendar only.",
            score=0.94,
            source_id="S-primary",
        ),
        Evidence(
            id="E3",
            document_id="D-thread",
            text="The target post asks what happened with this policy.",
            score=0.9,
            source_id="S-thread",
        ),
    ]


def _mixed_snippet_documents() -> list[ContextDocument]:
    return [
        ContextDocument(
            id="D-snippet",
            source_type="web",
            title="Snippet source",
            url="https://example.test/snippet",
            text="The policy passed because the committee confirmed the final vote.",
            metadata={"snippet_only": True, "citation_eligible": True},
        ),
        ContextDocument(
            id="D-primary",
            source_type="web",
            title="Primary source",
            url="https://example.test/primary",
            text="Primary source lists committee membership and meeting calendar only.",
            metadata={"citation_eligible": True},
        ),
        ContextDocument(
            id="D-thread",
            source_type="thread",
            title="Thread",
            url="https://example.test/thread",
            text="The target post asks what happened with this policy.",
            metadata={"citation_eligible": True},
        ),
    ]
