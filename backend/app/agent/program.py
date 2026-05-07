"""DSPy-owned explanation workflow with deterministic test-safe fallbacks."""

from __future__ import annotations

from collections.abc import Sequence
from time import perf_counter
from typing import Any

from app.agent.dspy_base import dspy_module_base
from app.agent.evidence_contract import (
    calibrated_runner_trust_flags,
    citable_evidence,
    combined_flags,
    snippet_only_source_ids,
    source_text_by_id,
)
from app.agent.finalize import FinalizationContext, finalize_explainer_run
from app.agent.quality_trace import AgentQualityTrace
from app.agent.runner import HeuristicSignatureRunner, QueryPlan, SignatureRunner
from app.agent.sources import sources_for_response
from app.agent.untrusted import scan_untrusted_flags
from app.guardrails.output import ExplanationDraft, OutputGuardrail, ValidationResult
from app.guardrails.policies import DEFAULT_POLICY, GuardrailPolicy
from app.guardrails.trust import TrustScorer
from app.schemas.api import ExplainRequest, ExplainResponse
from app.schemas.domain import ContextDocument, Evidence, PostContext, TraceEvent, TrustAssessment

_DspyModuleBase = dspy_module_base()


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
        provider_metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self._runner = runner or HeuristicSignatureRunner()
        self._trust_scorer = trust_scorer or TrustScorer(policy)
        self._output_guardrail = output_guardrail or OutputGuardrail(policy)
        self._policy = policy
        self.optimized_config = optimized_config or {}
        self.provider_metadata = provider_metadata or {}
        self.last_trace_events: list[TraceEvent] = []
        self.last_quality_trace: AgentQualityTrace | None = None
        self._revision_attempted = False
        self._revision_succeeded = False

    def forward(
        self,
        post: PostContext,
        evidence: Sequence[Evidence],
        *,
        documents: Sequence[ContextDocument] = (),
        request: ExplainRequest | None = None,
        warnings: Sequence[str] = (),
        retrieval_guardrail_flags: Sequence[str] = (),
    ) -> ExplainResponse:
        """DSPy-compatible forward method."""

        return self.explain_context(
            post=post,
            evidence=evidence,
            documents=documents,
            request=request,
            warnings=warnings,
            retrieval_guardrail_flags=retrieval_guardrail_flags,
        )

    def plan_queries(self, post: PostContext, *, reset_trace: bool = True) -> QueryPlan:
        """Classify the post and produce read-only retrieval intents before search."""

        if reset_trace:
            self.last_trace_events = []
        classification = self._classify(post)
        queries = self._queries(post, classification.category)
        return QueryPlan(category=classification.category, queries=queries)

    def scan_known_context(self, post: PostContext, *, reset_trace: bool = True) -> list[str]:
        """Scan visible post/thread/image text before it can influence retrieval planning."""

        if reset_trace:
            self.last_trace_events = []
        return self._scan_for_injection(post, (), (), include_post_context=True)

    def explain_context(
        self,
        *,
        post: PostContext,
        evidence: Sequence[Evidence],
        documents: Sequence[ContextDocument] = (),
        request: ExplainRequest | None = None,
        warnings: Sequence[str] = (),
        retrieval_guardrail_flags: Sequence[str] = (),
        pre_retrieval_guardrail_flags: Sequence[str] = (),
        planned_category: str | None = None,
        planned_queries: Sequence[str] | None = None,
        scan_post_context: bool = True,
        reset_trace: bool = True,
    ) -> ExplainResponse:
        """Explain a normalized post using retrieved evidence and guardrails."""

        started = perf_counter()
        self._reset_run_state(reset_trace=reset_trace)
        self._set_runner_documents(documents)
        injection_flags = self._scan_for_injection(
            post, evidence, documents, include_post_context=scan_post_context
        )
        category, queries = self._resolve_plan(post, planned_category, planned_queries)
        ranked_evidence = self._rerank(post, evidence)
        sources = sources_for_response(post, ranked_evidence, documents)
        allowed_source_ids = {source.id for source in sources}
        public_evidence = citable_evidence(ranked_evidence, allowed_source_ids)
        guardrail_flags = combined_flags(
            pre_retrieval_guardrail_flags, injection_flags, retrieval_guardrail_flags
        )
        pre_validation_trust = self._assess_initial_trust(
            post, public_evidence, guardrail_flags, documents
        )
        draft, validation_issues = self._generate_validated_draft(
            post, public_evidence, allowed_source_ids, documents
        )
        final_trust = self._assess_final_trust(
            post, public_evidence, pre_validation_trust.flags, validation_issues, documents
        )
        response, self.last_quality_trace = finalize_explainer_run(
            self,
            started=started,
            draft=draft,
            allowed_source_ids=allowed_source_ids,
            post=post,
            post_source_id=sources[0].id,
            sources=sources,
            category=category,
            queries=queries,
            warnings=warnings,
            validation_issues=validation_issues,
            trust=final_trust,
            evidence=public_evidence,
            documents=documents,
            request=request,
        )
        return response

    def _reset_run_state(self, *, reset_trace: bool) -> None:
        if reset_trace:
            self.last_trace_events = []
        self.last_quality_trace = None
        self._revision_attempted = False
        self._revision_succeeded = False

    def finalization_context(self) -> FinalizationContext:
        """Expose finalization state without requiring private attribute access."""

        return FinalizationContext(
            output_guardrail=self._output_guardrail,
            adapter_mode=self._runner.adapter_mode,
            adapter_notes=tuple(self._runner.adapter_notes),
            optimized_config=dict(self.optimized_config),
            trace_events=tuple(self.last_trace_events),
            provider_metadata=dict(self.provider_metadata),
            revision_attempted=self._revision_attempted,
            revision_succeeded=self._revision_succeeded,
        )

    def _resolve_plan(
        self,
        post: PostContext,
        planned_category: str | None,
        planned_queries: Sequence[str] | None,
    ) -> tuple[str, list[str]]:
        if planned_category is None or planned_queries is None:
            plan = self.plan_queries(post, reset_trace=False)
            return plan.category, plan.queries
        return planned_category, list(planned_queries)

    def _scan_for_injection(
        self,
        post: PostContext,
        evidence: Sequence[Evidence],
        documents: Sequence[ContextDocument],
        *,
        include_post_context: bool = True,
    ) -> list[str]:
        self._event("prompt_injection_scan", "started")
        flags = self._scan_untrusted_content(
            post,
            evidence,
            documents,
            include_post_context=include_post_context,
        )
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
        guardrail_flags: Sequence[str],
        documents: Sequence[ContextDocument],
    ) -> TrustAssessment:
        self._event("trust_assessment", "started")
        runner_assessment = self._runner.assess_evidence_trust(post, evidence)
        base_assessment = self._trust_scorer.assess(
            post,
            evidence,
            documents=documents,
            guardrail_flags=guardrail_flags,
        )
        runner_flags = calibrated_runner_trust_flags(runner_assessment.flags, base_assessment)
        assessment = self._trust_scorer.assess(
            post,
            evidence,
            documents=documents,
            guardrail_flags=[*guardrail_flags, *runner_flags],
        )
        self._event("trust_assessment", "completed", warnings=assessment.flags)
        return assessment

    def _generate_validated_draft(
        self,
        post: PostContext,
        evidence: Sequence[Evidence],
        allowed_source_ids: set[str],
        documents: Sequence[ContextDocument],
    ) -> tuple[ExplanationDraft, list[str]]:
        self._event("explain", "started", tool="dspy")
        draft = self._runner.explain(post, evidence)
        self._event("explain", "completed", tool="dspy")
        self._event("validate", "started", tool="dspy")
        validation = self._runner.validate(post, draft, evidence)
        draft, validation = self._revise_once_if_needed(
            post, evidence, documents, draft, validation, allowed_source_ids,
        )
        output_validation = self._output_guardrail.validate(
            draft,
            allowed_source_ids,
            source_text_by_id=source_text_by_id(evidence),
            snippet_only_source_ids=snippet_only_source_ids(documents, evidence),
        )
        if _only_language_issues(output_validation.issues):
            draft, output_validation = self._revise_once_if_needed(
                post, evidence, documents, draft, output_validation, allowed_source_ids,
            )
        elif output_validation.revised_bullets:
            draft = ExplanationDraft(bullets=output_validation.revised_bullets)
        validation_issues = validation.issues + output_validation.issues
        self._event("validate", "completed", tool="dspy", warnings=validation_issues)
        return draft, validation_issues

    def _revise_once_if_needed(
        self,
        post: PostContext,
        evidence: Sequence[Evidence],
        documents: Sequence[ContextDocument],
        draft: ExplanationDraft,
        validation: ValidationResult,
        allowed_source_ids: set[str],
    ) -> tuple[ExplanationDraft, ValidationResult]:
        if validation.is_valid:
            return draft, validation
        self._revision_attempted = True
        revised = self._runner.revise(post, draft, evidence, validation.issues)
        revision_validation = self._output_guardrail.validate(
            revised,
            allowed_source_ids,
            source_text_by_id=source_text_by_id(evidence),
            snippet_only_source_ids=snippet_only_source_ids(documents, evidence),
        )
        if revision_validation.is_valid:
            self._revision_succeeded = True
            return revised, revision_validation
        return draft, ValidationResult(
            is_valid=False,
            issues=list(dict.fromkeys([*validation.issues, *revision_validation.issues])),
            revised_bullets=validation.revised_bullets,
        )

    def _assess_final_trust(
        self,
        post: PostContext,
        evidence: Sequence[Evidence],
        guardrail_flags: Sequence[str],
        validation_issues: Sequence[str],
        documents: Sequence[ContextDocument],
    ) -> TrustAssessment:
        return self._trust_scorer.assess(
            post,
            evidence,
            documents=documents,
            guardrail_flags=[
                *guardrail_flags,
                *getattr(self._runner, "runtime_guardrail_flags", lambda: [])(),
            ],
            validation_issues=validation_issues,
        )

    def _set_runner_documents(self, documents: Sequence[ContextDocument]) -> None:
        setter = getattr(self._runner, "set_context_documents", None)
        if callable(setter):
            setter(documents)

    def _scan_untrusted_content(
        self,
        post: PostContext,
        evidence: Sequence[Evidence],
        documents: Sequence[ContextDocument],
        *,
        include_post_context: bool = True,
    ) -> list[str]:
        return scan_untrusted_flags(
            policy=self._policy,
            runner=self._runner,
            post=post,
            evidence=evidence,
            source_types={document.id: document.source_type for document in documents},
            include_post_context=include_post_context,
        )

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


def _only_language_issues(issues: Sequence[str]) -> bool:
    return bool(issues) and set(issues) <= {"non_english_output"}
