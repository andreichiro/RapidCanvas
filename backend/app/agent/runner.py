"""Signature runner implementations for DSPy and deterministic local tests."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import import_module
from typing import Literal, Protocol

from app.agent.signatures import build_dspy_signature_classes
from app.guardrails.output import BulletDraft, ExplanationDraft, OutputGuardrail, ValidationResult
from app.guardrails.policies import compact_text
from app.schemas.domain import Evidence, PostContext

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


class DspySignatureRunner:
    """Thin adapter around real DSPy Predict modules."""

    adapter_mode: AdapterMode = "none"
    adapter_notes: list[str] = ["DSPy Predict modules generated this workflow output."]

    def __init__(self) -> None:
        dspy = import_module("dspy")
        signatures = build_dspy_signature_classes()
        self._classify = dspy.Predict(signatures["ClassifyPostContext"])
        self._queries = dspy.Predict(signatures["GenerateSearchQueries"])
        self._explain = dspy.Predict(signatures["ExplainPost"])
        self._validate = dspy.Predict(signatures["ValidateExplanation"])

    def classify(self, post: PostContext) -> ClassificationResult:
        prediction = self._classify(
            post_text=_label("UNTRUSTED_POST_TEXT", post.text),
            thread_context=_label("UNTRUSTED_THREAD_CONTEXT", _thread_context(post)),
        )
        return ClassificationResult(
            category=str(getattr(prediction, "category", "unclassified")),
            rationale=str(getattr(prediction, "rationale", "")),
        )

    def generate_queries(self, post: PostContext, category: str) -> list[str]:
        prediction = self._queries(
            post_text=post.text,
            category=category,
            known_context=_thread_context(post),
        )
        return _json_list(str(getattr(prediction, "queries_json", "[]")))[:4]

    def explain(self, post: PostContext, evidence: Sequence[Evidence]) -> ExplanationDraft:
        prediction = self._explain(
            post_text=_label("UNTRUSTED_POST_TEXT", post.text),
            evidence=_evidence_json(evidence),
        )
        return _draft_from_json(str(getattr(prediction, "bullets_json", "[]")))

    def validate(
        self,
        post: PostContext,
        draft: ExplanationDraft,
        evidence: Sequence[Evidence],
    ) -> ValidationResult:
        prediction = self._validate(
            post_text=post.text,
            bullets_json=draft.model_dump_json(),
            evidence=_evidence_json(evidence),
        )
        return ValidationResult(
            is_valid=str(getattr(prediction, "is_valid", "false")).lower() == "true",
            issues=_json_list(str(getattr(prediction, "issues_json", "[]"))),
            revised_bullets=_draft_from_json(
                str(getattr(prediction, "revised_bullets_json", "[]"))
            ).bullets,
        )

    def revise(
        self,
        post: PostContext,
        draft: ExplanationDraft,
        evidence: Sequence[Evidence],
        issues: Sequence[str],
    ) -> ExplanationDraft:
        del issues
        validation = self.validate(post, draft, evidence)
        return ExplanationDraft(bullets=validation.revised_bullets)


def _thread_context(post: PostContext) -> str:
    parts = [*post.parent_texts, *post.quoted_texts]
    return "\n".join(compact_text(part, limit=400) for part in parts)


def _label(label: str, text: str) -> str:
    return f"{label}:\n{text}"


def _evidence_json(evidence: Sequence[Evidence]) -> str:
    payload = [
        {
            "id": item.id,
            "source_id": item.source_id,
            "score": item.score,
            "text": _label("UNTRUSTED_WEB_CONTEXT", compact_text(item.text, limit=800)),
        }
        for item in evidence
    ]
    return json.dumps(payload)


def _draft_from_json(value: str) -> ExplanationDraft:
    return ExplanationDraft(bullets=[_bullet_from_mapping(item) for item in _bullet_items(value)])


def _bullet_items(value: str) -> list[dict[str, object]]:
    parsed = _parse_json(value)
    if isinstance(parsed, dict):
        bullets = parsed.get("bullets", [])
        if isinstance(bullets, list):
            return [item for item in bullets if isinstance(item, dict)]
        return []
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return []


def _bullet_from_mapping(item: dict[str, object]) -> BulletDraft:
    text = item.get("text")
    source_ids = item.get("source_ids", [])
    if not isinstance(text, str):
        text = ""
    if not isinstance(source_ids, list):
        source_ids = []
    return BulletDraft(
        text=text or "Empty model bullet.",
        source_ids=[str(source) for source in source_ids],
    )


def _json_list(value: str) -> list[str]:
    parsed = _parse_json(value)
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _parse_json(value: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None
