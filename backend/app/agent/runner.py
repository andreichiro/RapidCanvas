"""Signature runner protocol and deterministic local implementation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from app.guardrails.output import BulletDraft, ExplanationDraft, OutputGuardrail, ValidationResult
from app.guardrails.policies import DEFAULT_POLICY, compact_text
from app.guardrails.trust import TrustScorer
from app.schemas.domain import Evidence, PostContext, TrustAssessment

AdapterMode = Literal["none", "deterministic_dev"]


@dataclass(frozen=True)
class ClassificationResult:
    """Structured post classification output."""

    category: str
    rationale: str


class SignatureRunner(Protocol):
    """Abstraction over DSPy predictors so tests can inject deterministic behavior."""

    adapter_mode: AdapterMode
    adapter_notes: list[str]

    def classify(self, post: PostContext) -> ClassificationResult:
        """Classify the post context."""

    def generate_queries(self, post: PostContext, category: str) -> list[str]:
        """Generate read-only search queries."""

    def detect_prompt_injection(
        self,
        content: str,
        label: str = "UNTRUSTED_WEB_CONTEXT",
    ) -> list[str]:
        """Return prompt-injection guardrail flags for labeled untrusted content."""

    def rerank_evidence(self, post: PostContext, evidence: Sequence[Evidence]) -> list[Evidence]:
        """Rerank evidence for explanation usefulness."""

    def assess_evidence_trust(
        self,
        post: PostContext,
        evidence: Sequence[Evidence],
    ) -> TrustAssessment:
        """Assess evidence trust through the runner path."""

    def explain(self, post: PostContext, evidence: Sequence[Evidence]) -> ExplanationDraft:
        """Generate a structured cited explanation draft."""

    def validate(
        self,
        post: PostContext,
        draft: ExplanationDraft,
        evidence: Sequence[Evidence],
    ) -> ValidationResult:
        """Validate and optionally revise a draft."""

    def revise(
        self,
        post: PostContext,
        draft: ExplanationDraft,
        evidence: Sequence[Evidence],
        issues: Sequence[str],
    ) -> ExplanationDraft:
        """Perform one revision attempt."""

    def judge_evaluation_case(
        self,
        expected: str,
        prediction: str,
        evidence: Sequence[Evidence],
    ) -> dict[str, float | list[str]]:
        """Judge an eval case using the DSPy judge signature."""


class HeuristicSignatureRunner:
    """Deterministic runner used for unit tests and no-key local development."""

    adapter_mode: AdapterMode = "deterministic_dev"
    adapter_notes: list[str] = [
        "DSPy signatures are defined, but deterministic Dev C runner handled this call.",
        "Use backend optional AI dependencies and provider credentials for live DSPy prediction.",
    ]

    def classify(self, post: PostContext) -> ClassificationResult:
        text = post.text.lower()
        if post.images:
            category = "image_context"
        elif post.links:
            category = "link_context"
        elif "?" in post.text:
            category = "question"
        elif any(marker in text for marker in ("breaking", "news", "today")):
            category = "news"
        else:
            category = "general_context"
        return ClassificationResult(category=category, rationale="Heuristic local category.")

    def generate_queries(self, post: PostContext, category: str) -> list[str]:
        base = compact_text(post.text, limit=90)
        if not base:
            return [f"{post.author} Bluesky {category} context"]
        return [f"{base} {category} context"]

    def detect_prompt_injection(
        self,
        content: str,
        label: str = "UNTRUSTED_WEB_CONTEXT",
    ) -> list[str]:
        del label
        return ["prompt_injection_risk"] if DEFAULT_POLICY.prompt_injection_hits(content) else []

    def rerank_evidence(self, post: PostContext, evidence: Sequence[Evidence]) -> list[Evidence]:
        del post
        return sorted(evidence, key=lambda item: item.score, reverse=True)

    def assess_evidence_trust(
        self,
        post: PostContext,
        evidence: Sequence[Evidence],
    ) -> TrustAssessment:
        return TrustScorer().assess(post, evidence)

    def explain(self, post: PostContext, evidence: Sequence[Evidence]) -> ExplanationDraft:
        del post
        bullets: list[BulletDraft] = []
        for item in sorted(evidence, key=lambda entry: entry.score, reverse=True)[:5]:
            snippet = compact_text(item.text, limit=230)
            bullets.append(
                BulletDraft(
                    text=f"Source-backed context: {snippet}",
                    source_ids=[item.source_id],
                )
            )
        return ExplanationDraft(bullets=bullets)

    def validate(
        self,
        post: PostContext,
        draft: ExplanationDraft,
        evidence: Sequence[Evidence],
    ) -> ValidationResult:
        del post
        return OutputGuardrail().validate(draft, {item.source_id for item in evidence})

    def revise(
        self,
        post: PostContext,
        draft: ExplanationDraft,
        evidence: Sequence[Evidence],
        issues: Sequence[str],
    ) -> ExplanationDraft:
        del post, issues
        allowed = {item.source_id for item in evidence}
        revised = [
            bullet
            for bullet in draft.bullets
            if bullet.source_ids and all(source_id in allowed for source_id in bullet.source_ids)
        ]
        return ExplanationDraft(bullets=revised)

    def judge_evaluation_case(
        self,
        expected: str,
        prediction: str,
        evidence: Sequence[Evidence],
    ) -> dict[str, float | list[str]]:
        del evidence
        expected_terms = [term for term in expected.lower().split() if len(term) > 3]
        matched = sum(1 for term in expected_terms if term in prediction.lower())
        recall = matched / len(expected_terms) if expected_terms else 1.0
        return {"score": round(recall, 3), "error_labels": [] if recall >= 0.5 else ["low_recall"]}
