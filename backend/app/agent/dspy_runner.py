"""Live DSPy signature runner."""

from __future__ import annotations

import json
from collections.abc import Sequence
from importlib import import_module
from typing import Any, cast

from app.agent.runner import AdapterMode, ClassificationResult
from app.agent.signatures import build_dspy_signature_classes
from app.agent.untrusted import evidence_untrusted_label
from app.guardrails.output import BulletDraft, ExplanationDraft, ValidationResult
from app.guardrails.policies import compact_text
from app.schemas.domain import (
    ContextDocument,
    Evidence,
    FallbackMode,
    PostContext,
    SourceType,
    TrustAssessment,
)


class DspySignatureRunner:
    """Thin adapter around real DSPy Predict modules."""

    adapter_mode: AdapterMode = "none"
    adapter_notes: list[str] = ["DSPy Predict modules generated this workflow output."]

    def __init__(self, optimized_explain_program: Any | None = None) -> None:
        dspy = import_module("dspy")
        signatures = build_dspy_signature_classes()
        self._document_source_types: dict[str, SourceType] = {}
        self._optimized_explain_program = optimized_explain_program
        self._classify = dspy.Predict(signatures["ClassifyPostContext"])
        self._queries = dspy.Predict(signatures["GenerateSearchQueries"])
        self._detect = dspy.Predict(signatures["DetectPromptInjectionRisk"])
        self._rerank = dspy.Predict(signatures["RerankEvidence"])
        self._assess = dspy.Predict(signatures["AssessEvidenceTrust"])
        self._explain = dspy.Predict(signatures["ExplainPost"])
        self._validate = dspy.Predict(signatures["ValidateExplanation"])
        self._judge = dspy.Predict(signatures["JudgeEvaluationCase"])

    def set_context_documents(self, documents: Sequence[ContextDocument]) -> None:
        """Record evidence document types so prompts can use precise untrusted labels."""

        self._document_source_types = {document.id: document.source_type for document in documents}

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
            post_text=_label("UNTRUSTED_POST_TEXT", post.text),
            category=category,
            known_context=_label("UNTRUSTED_THREAD_CONTEXT", _thread_context(post)),
        )
        return _json_list(str(getattr(prediction, "queries_json", "[]")))[:4]

    def detect_prompt_injection(
        self,
        content: str,
        label: str = "UNTRUSTED_WEB_CONTEXT",
    ) -> list[str]:
        prediction = self._detect(content=_label(label, content))
        risk = str(getattr(prediction, "risk", "none")).lower()
        reasons = _json_list(str(getattr(prediction, "reasons_json", "[]")))
        if risk in {"medium", "high"} or reasons:
            return ["prompt_injection_risk"]
        return []

    def rerank_evidence(self, post: PostContext, evidence: Sequence[Evidence]) -> list[Evidence]:
        prediction = self._rerank(
            post_text=_label("UNTRUSTED_POST_TEXT", post.text),
            candidate_evidence=_evidence_json(evidence, self._document_source_types),
        )
        ranked_ids = _json_list(str(getattr(prediction, "ranked_evidence_json", "[]")))
        by_id = {item.id: item for item in evidence}
        ranked = [by_id[item_id] for item_id in ranked_ids if item_id in by_id]
        ranked_id_set = {ranked_item.id for ranked_item in ranked}
        remaining = [item for item in evidence if item.id not in ranked_id_set]
        return [*ranked, *remaining]

    def assess_evidence_trust(
        self,
        post: PostContext,
        evidence: Sequence[Evidence],
    ) -> TrustAssessment:
        prediction = self._assess(
            post_text=_label("UNTRUSTED_POST_TEXT", post.text),
            evidence=_evidence_json(evidence, self._document_source_types),
        )
        score = _float_or_default(str(getattr(prediction, "trust_score", "0.0")), 0.0)
        fallback = _fallback_mode(str(getattr(prediction, "fallback_mode", "abstain")))
        return TrustAssessment(
            score=max(0.0, min(1.0, score)),
            fallback_mode=fallback,
            flags=[] if fallback == "none" else [f"dspy_trust_{fallback}"],
            reasons=_json_list(str(getattr(prediction, "reasons_json", "[]"))),
        )

    def explain(self, post: PostContext, evidence: Sequence[Evidence]) -> ExplanationDraft:
        inputs = {
            "post_text": _label("UNTRUSTED_POST_TEXT", post.text),
            "evidence": _evidence_json(evidence, self._document_source_types),
        }
        if self._optimized_explain_program is not None:
            prediction = self._optimized_explain_program(**inputs, expected_points=[])
        else:
            prediction = self._explain(**inputs)
        return _draft_from_json(str(getattr(prediction, "bullets_json", "[]")))

    def validate(
        self,
        post: PostContext,
        draft: ExplanationDraft,
        evidence: Sequence[Evidence],
    ) -> ValidationResult:
        prediction = self._validate(
            post_text=_label("UNTRUSTED_POST_TEXT", post.text),
            bullets_json=draft.model_dump_json(),
            evidence=_evidence_json(evidence, self._document_source_types),
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

    def judge_evaluation_case(
        self,
        expected: str,
        prediction: str,
        evidence: Sequence[Evidence],
    ) -> dict[str, float | list[str]]:
        judged = self._judge(
            expected=expected,
            prediction=prediction,
            evidence=_evidence_json(evidence, self._document_source_types),
        )
        scores = _json_mapping(str(getattr(judged, "scores_json", "{}")))
        labels = _json_list(str(getattr(judged, "error_labels_json", "[]")))
        score = _float_or_default(str(scores.get("score", 0.0)), 0.0)
        return {"score": score, "error_labels": labels}


def _thread_context(post: PostContext) -> str:
    parts = [*post.parent_texts, *post.quoted_texts]
    return "\n".join(compact_text(part, limit=400) for part in parts)


def _label(label: str, text: str) -> str:
    return f"{label}:\n{text}"


def _evidence_json(
    evidence: Sequence[Evidence],
    document_source_types: dict[str, SourceType] | None = None,
) -> str:
    source_types = document_source_types or {}
    payload = [
        {
            "id": item.id,
            "source_id": item.source_id,
            "score": item.score,
            "text": _label(
                evidence_untrusted_label(item, source_types),
                compact_text(item.text, limit=800),
            ),
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


def _fallback_mode(value: str) -> FallbackMode:
    if value in {"none", "partial", "abstain", "safe_summary"}:
        return cast(FallbackMode, value)
    return "abstain"


def _json_list(value: str) -> list[str]:
    parsed = _parse_json(value)
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _json_mapping(value: str) -> dict[str, object]:
    parsed = _parse_json(value)
    return parsed if isinstance(parsed, dict) else {}


def _float_or_default(value: str, default: float) -> float:
    try:
        return float(value)
    except ValueError:
        return default


def _parse_json(value: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None
