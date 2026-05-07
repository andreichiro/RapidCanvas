"""Live DSPy signature runner."""

from __future__ import annotations

from collections.abc import Sequence
from importlib import import_module
from typing import Any

from app.agent import dspy_parsing as parsed
from app.agent.runner import (
    DETERMINISTIC_FALLBACK_ADAPTER,
    AdapterMode,
    ClassificationResult,
    HeuristicSignatureRunner,
)
from app.agent.signatures import build_dspy_signature_classes
from app.guardrails.output import (
    ExplanationDraft,
    ValidationResult,
    text_appears_non_english,
)
from app.schemas.domain import (
    ContextDocument,
    Evidence,
    PostContext,
    SourceType,
    TrustAssessment,
)


class DspySignatureRunner:
    def __init__(self, optimized_explain_program: Any | None = None) -> None:
        dspy = import_module("dspy")
        signatures = build_dspy_signature_classes()
        self.adapter_mode: AdapterMode = "none"
        self.adapter_notes = ["DSPy Predict modules generated this workflow output."]
        self._fallback = HeuristicSignatureRunner()
        self._runtime_guardrail_flags: list[str] = []
        self._document_source_types: dict[str, SourceType] = {}
        self._optimized_explain_program = optimized_explain_program
        self._classify = dspy.Predict(signatures["ClassifyPostContext"])
        self._queries = dspy.Predict(signatures["GenerateSearchQueries"])
        self._detect = dspy.Predict(signatures["DetectPromptInjectionRisk"])
        self._rerank = dspy.Predict(signatures["RerankEvidence"])
        self._assess = dspy.Predict(signatures["AssessEvidenceTrust"])
        self._explain = dspy.Predict(signatures["ExplainPost"])
        self._validate = dspy.Predict(signatures["ValidateExplanation"])
        self._ensure_english = dspy.Predict(signatures["EnsureEnglishExplanation"])
        self._judge = dspy.Predict(signatures["JudgeEvaluationCase"])

    def set_context_documents(self, documents: Sequence[ContextDocument]) -> None:
        self._document_source_types = {document.id: document.source_type for document in documents}

    def classify(self, post: PostContext) -> ClassificationResult:
        prediction = self._predict(
            "classify",
            self._classify,
            post_text=parsed.label("UNTRUSTED_POST_TEXT", post.text),
            thread_context=parsed.label("UNTRUSTED_THREAD_CONTEXT", parsed.thread_context(post)),
        )
        if prediction is None:
            return self._fallback.classify(post)
        return ClassificationResult(
            category=str(getattr(prediction, "category", "unclassified")),
            rationale=str(getattr(prediction, "rationale", "")),
        )

    def generate_queries(self, post: PostContext, category: str) -> list[str]:
        prediction = self._predict(
            "query_generation",
            self._queries,
            post_text=parsed.label("UNTRUSTED_POST_TEXT", post.text),
            category=category,
            known_context=parsed.label("UNTRUSTED_THREAD_CONTEXT", parsed.thread_context(post)),
        )
        if prediction is None:
            return self._fallback.generate_queries(post, category)
        return parsed.json_list(str(getattr(prediction, "queries_json", "[]")))[:4]

    def detect_prompt_injection(
        self,
        content: str,
        label: str = "UNTRUSTED_WEB_CONTEXT",
    ) -> list[str]:
        prediction = self._predict(
            "prompt_injection_detection",
            self._detect,
            content=parsed.label(label, content),
        )
        if prediction is None:
            fallback_flags = self._fallback.detect_prompt_injection(content, label)
            return list(dict.fromkeys(["dspy_provider_error", *fallback_flags]))
        risk = str(getattr(prediction, "risk", "none")).lower()
        reasons = parsed.json_list(str(getattr(prediction, "reasons_json", "[]")))
        if risk in {"medium", "high"} or reasons:
            return ["prompt_injection_risk"]
        return []

    def rerank_evidence(self, post: PostContext, evidence: Sequence[Evidence]) -> list[Evidence]:
        prediction = self._predict(
            "rerank",
            self._rerank,
            post_text=parsed.label("UNTRUSTED_POST_TEXT", post.text),
            candidate_evidence=parsed.evidence_json(evidence, self._document_source_types),
        )
        if prediction is None:
            return self._fallback.rerank_evidence(post, evidence)
        ranked_ids = parsed.json_list(str(getattr(prediction, "ranked_evidence_json", "[]")))
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
        prediction = self._predict(
            "trust_assessment",
            self._assess,
            post_text=parsed.label("UNTRUSTED_POST_TEXT", post.text),
            evidence=parsed.evidence_json(evidence, self._document_source_types),
        )
        if prediction is None:
            assessment = self._fallback.assess_evidence_trust(post, evidence)
            return TrustAssessment(
                score=min(assessment.score, 0.4),
                fallback_mode="safe_summary",
                flags=list(dict.fromkeys([*assessment.flags, "dspy_provider_error"])),
                reasons=[
                    *assessment.reasons,
                    "DSPy provider call failed; guarded fallback was used.",
                ],
            )
        score = parsed.float_or_default(str(getattr(prediction, "trust_score", "0.0")), 0.0)
        fallback = parsed.fallback_mode(str(getattr(prediction, "fallback_mode", "abstain")))
        return TrustAssessment(
            score=max(0.0, min(1.0, score)),
            fallback_mode=fallback,
            flags=[] if fallback == "none" else [f"dspy_trust_{fallback}"],
            reasons=parsed.json_list(str(getattr(prediction, "reasons_json", "[]"))),
        )

    def explain(self, post: PostContext, evidence: Sequence[Evidence]) -> ExplanationDraft:
        inputs = {
            "post_text": parsed.label("UNTRUSTED_POST_TEXT", post.text),
            "evidence": parsed.evidence_json(evidence, self._document_source_types),
        }
        if self._optimized_explain_program is not None:
            prediction = self._predict(
                "explain",
                self._optimized_explain_program,
                **inputs,
                expected_points=[],
            )
        else:
            prediction = self._predict("explain", self._explain, **inputs)
        if prediction is None:
            return self._fallback.explain(post, evidence)
        return parsed.normalize_draft_source_ids(
            parsed.draft_from_json(str(getattr(prediction, "bullets_json", "[]"))),
            evidence,
        )

    def validate(
        self,
        post: PostContext,
        draft: ExplanationDraft,
        evidence: Sequence[Evidence],
    ) -> ValidationResult:
        prediction = self._predict(
            "validate",
            self._validate,
            post_text=parsed.label("UNTRUSTED_POST_TEXT", post.text),
            bullets_json=draft.model_dump_json(),
            evidence=parsed.evidence_json(evidence, self._document_source_types),
        )
        if prediction is None:
            return self._fallback.validate(post, draft, evidence)
        revised_draft = parsed.normalize_draft_source_ids(
            parsed.draft_from_json(str(getattr(prediction, "revised_bullets_json", "[]"))),
            evidence,
        )
        return ValidationResult(
            is_valid=str(getattr(prediction, "is_valid", "false")).lower() == "true",
            issues=parsed.validation_issue_labels(str(getattr(prediction, "issues_json", "[]"))),
            revised_bullets=revised_draft.bullets,
        )

    def revise(
        self,
        post: PostContext,
        draft: ExplanationDraft,
        evidence: Sequence[Evidence],
        issues: Sequence[str],
    ) -> ExplanationDraft:
        if "non_english_output" in issues:
            translated = self._translate_draft_to_english(draft, evidence)
            if translated is not None:
                return translated
        validation = self.validate(post, draft, evidence)
        return ExplanationDraft(bullets=validation.revised_bullets)

    def judge_evaluation_case(
        self,
        expected: str,
        prediction: str,
        evidence: Sequence[Evidence],
    ) -> dict[str, float | list[str]]:
        judged = self._predict(
            "judge_evaluation_case",
            self._judge,
            expected=expected,
            prediction=prediction,
            evidence=parsed.evidence_json(evidence, self._document_source_types),
        )
        if judged is None:
            return self._fallback.judge_evaluation_case(expected, prediction, evidence)
        scores = parsed.json_mapping(str(getattr(judged, "scores_json", "{}")))
        labels = parsed.json_list(str(getattr(judged, "error_labels_json", "[]")))
        score = parsed.float_or_default(str(scores.get("score", 0.0)), 0.0)
        return {"score": score, "error_labels": labels}

    def runtime_guardrail_flags(self) -> list[str]:
        return list(dict.fromkeys(self._runtime_guardrail_flags))

    def _predict(self, step: str, predictor: Any, **kwargs: Any) -> Any | None:
        if "dspy_provider_error" in self._runtime_guardrail_flags:
            return None
        try:
            return predictor(**kwargs)
        except Exception as exc:
            self._record_provider_failure(step, exc)
            return None

    def _record_provider_failure(self, step: str, exc: Exception) -> None:
        self.adapter_mode = DETERMINISTIC_FALLBACK_ADAPTER
        self._runtime_guardrail_flags.append("dspy_provider_error")
        note = f"DSPy provider failed during {step}; guarded fallback handled it."
        detail = f"DSPy provider error class: {exc.__class__.__name__}."
        for item in (note, detail):
            if item not in self.adapter_notes:
                self.adapter_notes.append(item)

    def _translate_draft_to_english(
        self,
        draft: ExplanationDraft,
        evidence: Sequence[Evidence],
    ) -> ExplanationDraft | None:
        if not any(text_appears_non_english(bullet.text) for bullet in draft.bullets):
            return draft
        prediction = self._predict(
            "english_output_repair",
            self._ensure_english,
            bullets_json=draft.model_dump_json(),
        )
        if prediction is None:
            return None
        return parsed.normalize_draft_source_ids(
            parsed.draft_from_json(str(getattr(prediction, "translated_bullets_json", "[]"))),
            evidence,
        )


_evidence_json = parsed.evidence_json
_float_or_default = parsed.float_or_default
_normalize_draft_source_ids = parsed.normalize_draft_source_ids
