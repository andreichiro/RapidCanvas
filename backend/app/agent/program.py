"""DSPy-owned explanation workflow with deterministic test-safe fallbacks."""

from __future__ import annotations

from collections.abc import Sequence
from importlib import import_module
from time import perf_counter
from typing import Any, cast

from app.agent.runner import HeuristicSignatureRunner, SignatureRunner
from app.agent.sources import sources_for_response
from app.guardrails.output import ExplanationDraft, OutputGuardrail, ValidationResult
from app.guardrails.policies import DEFAULT_POLICY, GuardrailPolicy
from app.guardrails.trust import TrustScorer
from app.schemas.api import ExplainRequest, ExplainResponse, PostSummary, Trace
from app.schemas.domain import ContextDocument, Evidence, PostContext, TraceEvent, TrustAssessment


def _dspy_module_base() -> type[Any]:
    try:
        dspy = import_module("dspy")
    except ImportError:
        return object
    return cast(type[Any], dspy.Module)


_DspyModuleBase = _dspy_module_base()


class BlueskyExplainer(_DspyModuleBase):  # type: ignore[misc, valid-type]
    """Agent workflow from post/evidence to guarded public API response."""

    def __init__(
        self,
        *,
        runner: SignatureRunner | None = None,
        trust_scorer: TrustScorer | None = None,
        output_guardrail: OutputGuardrail | None = None,
        policy: GuardrailPolicy = DEFAULT_POLICY,
        optimized_config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self._runner = runner or HeuristicSignatureRunner()
        self._trust_scorer = trust_scorer or TrustScorer(policy)
        self._output_guardrail = output_guardrail or OutputGuardrail(policy)
        self._policy = policy
        self.optimized_config = optimized_config or {}
        self.last_trace_events: list[TraceEvent] = []

    def forward(
        self,
        post: PostContext,
        evidence: Sequence[Evidence],
        *,
        documents: Sequence[ContextDocument] = (),
        request: ExplainRequest | None = None,
        warnings: Sequence[str] = (),
    ) -> ExplainResponse:
        """DSPy-compatible forward method."""

        return self.explain_context(
            post=post,
            evidence=evidence,
            documents=documents,
            request=request,
            warnings=warnings,
        )

    def explain_context(
        self,
        *,
        post: PostContext,
        evidence: Sequence[Evidence],
        documents: Sequence[ContextDocument] = (),
        request: ExplainRequest | None = None,
        warnings: Sequence[str] = (),
    ) -> ExplainResponse:
        """Explain a normalized post using retrieved evidence and guardrails."""

        del request
        started = perf_counter()
        self.last_trace_events = []
        self._set_runner_documents(documents)
        injection_flags = self._scan_for_injection(post, evidence)
        classification = self._classify(post)
        queries = self._queries(post, classification.category)
        ranked_evidence = self._rerank(post, evidence)
        sources = sources_for_response(post, ranked_evidence, documents)
        allowed_source_ids = {source.id for source in sources}
        post_source_id = sources[0].id
        pre_validation_trust = self._assess_initial_trust(post, ranked_evidence, injection_flags)
        draft, validation_issues = self._generate_validated_draft(
            post,
            ranked_evidence,
            allowed_source_ids,
        )
        final_trust = self._assess_final_trust(
            post,
            ranked_evidence,
            pre_validation_trust.flags,
            validation_issues,
        )
        bullets = self._output_guardrail.repair(
            draft,
            allowed_source_ids,
            fallback_mode=final_trust.fallback_mode,
            post=post,
            post_source_id=post_source_id,
        )
        return self._response(
            post=post,
            sources=sources,
            bullets=bullets,
            category=classification.category,
            queries=queries,
            warnings=warnings,
            validation_issues=validation_issues,
            trust=final_trust,
            latency_ms=int((perf_counter() - started) * 1000),
        )

    def _scan_for_injection(self, post: PostContext, evidence: Sequence[Evidence]) -> list[str]:
        self._event("prompt_injection_scan", "started")
        flags = self._scan_untrusted_content(post, evidence)
        self._event("prompt_injection_scan", "completed", warnings=flags)
        return flags

    def _classify(self, post: PostContext) -> Any:
        self._event("classify", "started", tool="dspy")
        classification = self._runner.classify(post)
        self._event("classify", "completed", tool="dspy")
        return classification

    def _rerank(self, post: PostContext, evidence: Sequence[Evidence]) -> list[Evidence]:
        self._event("rerank", "started", tool="dspy")
        ranked = self._runner.rerank_evidence(post, evidence)
        self._event("rerank", "completed", tool="dspy")
        return ranked

    def _queries(self, post: PostContext, category: str) -> list[str]:
        self._event("query_generation", "started", tool="dspy")
        queries = self._runner.generate_queries(post, category)
        self._event("query_generation", "completed", tool="dspy")
        return queries

    def _assess_initial_trust(
        self,
        post: PostContext,
        evidence: Sequence[Evidence],
        injection_flags: Sequence[str],
    ) -> TrustAssessment:
        self._event("trust_assessment", "started")
        runner_assessment = self._runner.assess_evidence_trust(post, evidence)
        assessment = self._trust_scorer.assess(
            post,
            evidence,
            guardrail_flags=[*injection_flags, *runner_assessment.flags],
        )
        self._event("trust_assessment", "completed", warnings=assessment.flags)
        return assessment

    def _generate_validated_draft(
        self,
        post: PostContext,
        evidence: Sequence[Evidence],
        allowed_source_ids: set[str],
    ) -> tuple[ExplanationDraft, list[str]]:
        self._event("explain", "started", tool="dspy")
        draft = self._runner.explain(post, evidence)
        self._event("explain", "completed", tool="dspy")
        self._event("validate", "started", tool="dspy")
        validation = self._runner.validate(post, draft, evidence)
        draft, validation = self._revise_once_if_needed(post, evidence, draft, validation)
        output_validation = self._output_guardrail.validate(draft, allowed_source_ids)
        validation_issues = validation.issues + output_validation.issues
        self._event("validate", "completed", tool="dspy", warnings=validation_issues)
        return draft, validation_issues

    def _revise_once_if_needed(
        self,
        post: PostContext,
        evidence: Sequence[Evidence],
        draft: ExplanationDraft,
        validation: ValidationResult,
    ) -> tuple[ExplanationDraft, ValidationResult]:
        if validation.is_valid:
            return draft, validation
        revised = self._runner.revise(post, draft, evidence, validation.issues)
        allowed_source_ids = {item.source_id for item in evidence}
        revision_validation = self._output_guardrail.validate(revised, allowed_source_ids)
        if revision_validation.is_valid:
            return revised, revision_validation
        return draft, validation

    def _assess_final_trust(
        self,
        post: PostContext,
        evidence: Sequence[Evidence],
        guardrail_flags: Sequence[str],
        validation_issues: Sequence[str],
    ) -> TrustAssessment:
        return self._trust_scorer.assess(
            post,
            evidence,
            guardrail_flags=guardrail_flags,
            validation_issues=validation_issues,
        )

    def _response(
        self,
        *,
        post: PostContext,
        sources: list[Any],
        bullets: list[Any],
        category: str,
        queries: list[str],
        warnings: Sequence[str],
        validation_issues: Sequence[str],
        trust: TrustAssessment,
        latency_ms: int,
    ) -> ExplainResponse:
        trace_warnings = self._trace_warnings(warnings, trust, validation_issues)
        return ExplainResponse(
            post=PostSummary(
                url=post.url,
                author=post.author,
                text=post.text,
                created_at=post.created_at,
            ),
            bullets=bullets,
            sources=sources,
            trace=Trace(
                category=category,
                queries=queries,
                warnings=trace_warnings,
                latency_ms=latency_ms,
                trust_score=trust.score,
                fallback_mode=trust.fallback_mode,
                guardrail_flags=_dedupe([*trust.flags, *validation_issues]),
                adapter_mode=self._runner.adapter_mode,
                adapter_notes=self._runner.adapter_notes,
            ),
        )

    def _set_runner_documents(self, documents: Sequence[ContextDocument]) -> None:
        setter = getattr(self._runner, "set_context_documents", None)
        if callable(setter):
            setter(documents)

    def _trace_warnings(
        self,
        warnings: Sequence[str],
        trust: TrustAssessment,
        validation_issues: Sequence[str],
    ) -> list[str]:
        optimized = (
            ["optimized_program_loaded"] if self.optimized_config.get("schema_version") else []
        )
        return _dedupe([*warnings, *trust.reasons, *validation_issues, *optimized])

    def _scan_untrusted_content(
        self,
        post: PostContext,
        evidence: Sequence[Evidence],
    ) -> list[str]:
        content = [
            post.text,
            *post.parent_texts,
            *post.quoted_texts,
            *(image.alt_text or "" for image in post.images),
            *(item.text for item in evidence),
        ]
        hits: list[str] = []
        for item in content:
            hits.extend(self._policy.prompt_injection_hits(item))
            hits.extend(self._runner.detect_prompt_injection(item))
        return ["prompt_injection_risk"] if hits else []

    def _event(
        self,
        step: str,
        status: str,
        *,
        tool: str | None = None,
        warnings: Sequence[str] = (),
    ) -> None:
        self.last_trace_events.append(
            TraceEvent(
                step=step,
                status=status,
                tool=tool,
                latency_ms=0,
                warnings=list(warnings),
            )
        )


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped
