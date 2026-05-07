"""Route-compatible service wrapper for the runtime agent program."""

from __future__ import annotations

from collections.abc import Sequence
from inspect import Parameter, signature
from typing import Any, Protocol

from app.agent.adaptive_retrieval import merge_bundles, should_run_adaptive_round
from app.agent.evidence_contract import (
    EvidenceBundle,
    RetrievalOutput,
    normalize_retrieval_output,
)
from app.agent.loader import load_program
from app.agent.program import BlueskyExplainer
from app.agent.quality_trace import AgentQualityTrace
from app.agent.query_planning import adaptive_runtime_queries, runtime_queries
from app.agent.runner import QueryPlan
from app.config import Settings, get_settings
from app.schemas.api import ExplainRequest, ExplainResponse
from app.schemas.domain import ContextDocument, Evidence, PostContext


class ThreadContextFallbackRetriever:
    """Fallback retriever using normalized Bluesky thread context as evidence."""

    warnings: Sequence[str] = (
        "search_rag_not_connected_using_thread_context_evidence",
        "thread_context_fallback_guardrails_active",
    )

    def retrieve(
        self,
        post: PostContext,
        queries: Sequence[str] = (),
    ) -> tuple[Sequence[Evidence], Sequence[ContextDocument]]:
        del queries
        documents = self._documents(post)
        evidence = [
            Evidence(
                id=f"E{index}",
                document_id=document.id,
                text=document.text,
                score=float(document.metadata.get("score", 0.55)),
                source_id=f"S{index}",
            )
            for index, document in enumerate(documents, start=1)
            if document.text.strip()
        ]
        return evidence, documents

    def _documents(self, post: PostContext) -> list[ContextDocument]:
        documents = [
            ContextDocument(
                id="D1",
                source_type="thread",
                title=f"Bluesky post by {post.author}",
                url=post.url,
                text=post.text or "The fetched post has no text.",
                metadata={"score": 0.72},
            )
        ]
        documents.extend(
            ContextDocument(
                id=f"DP{index}",
                source_type="thread",
                title="Bluesky parent context",
                url=post.url,
                text=text,
                metadata={"score": 0.66},
            )
            for index, text in enumerate(post.parent_texts, start=1)
        )
        documents.extend(
            ContextDocument(
                id=f"DQ{index}",
                source_type="thread",
                title="Bluesky quoted context",
                url=post.url,
                text=text,
                metadata={"score": 0.62},
            )
            for index, text in enumerate(post.quoted_texts, start=1)
        )
        documents.extend(
            ContextDocument(
                id=f"DI{index}",
                source_type="image",
                title="Bluesky image alt text",
                url=image.url,
                text=image.alt_text or "Image was present but had no alt text.",
                metadata={"score": 0.5},
            )
            for index, image in enumerate(post.images, start=1)
        )
        return documents


class PostContextFetcher(Protocol):
    """Protocol for a normalized Bluesky context fetcher."""

    def fetch_context(self, url: str) -> PostContext:
        """Fetch a normalized public post context."""


class EvidenceRetriever(Protocol):
    @property
    def warnings(self) -> Sequence[str]:
        """Non-fatal retrieval warnings for trace output."""

    def retrieve(self, post: PostContext, queries: Sequence[str] = ()) -> RetrievalOutput:
        """Retrieve evidence and source documents for a post."""


class AgentExplainerService:
    """Route-compatible service that wires fetch, retrieval, and the agent program."""

    def __init__(
        self,
        *,
        fetcher: PostContextFetcher,
        retriever: EvidenceRetriever,
        program: BlueskyExplainer | None = None,
        settings: Settings | None = None,
        extra_warnings: Sequence[str] = (),
    ) -> None:
        self._fetcher = fetcher
        self._retriever = retriever
        self._program = program
        self._settings = settings
        self._program_cache: dict[str, tuple[BlueskyExplainer, list[str]]] = {}
        self._extra_warnings = extra_warnings
        self.last_quality_trace: AgentQualityTrace | None = None

    def explain(self, request: ExplainRequest) -> ExplainResponse:
        program, program_warnings = self._program_for_request(request)
        post = self._fetcher.fetch_context(request.post_url)
        pre_retrieval_flags = program.scan_known_context(post)
        plan, plan_warnings = self._plan_queries(program, post, pre_retrieval_flags)
        bundle, retrieval_warnings, trace_queries = self._retrieve_with_optional_adaptive(
            post,
            plan,
            allow_adaptive="prompt_injection_risk" not in pre_retrieval_flags,
        )
        warnings = _dedupe(
            [
                *post.warnings,
                *bundle.warnings,
                *bundle.source_safety_diagnostics,
                *program_warnings,
                *plan_warnings,
                *retrieval_warnings,
                *self._extra_warnings,
            ]
        )
        response = program.explain_context(
            post=post,
            evidence=bundle.evidence,
            documents=bundle.documents,
            request=request,
            warnings=warnings,
            retrieval_guardrail_flags=[
                *bundle.guardrail_flags,
                *_retrieval_warning_flags(bundle.warnings),
            ],
            pre_retrieval_guardrail_flags=pre_retrieval_flags,
            planned_category=plan.category,
            planned_queries=trace_queries,
            scan_post_context=False,
            reset_trace=False,
        )
        self.last_quality_trace = program.last_quality_trace
        return response

    def _program_for_request(self, request: ExplainRequest) -> tuple[BlueskyExplainer, list[str]]:
        if self._program is not None:
            return self._program, []
        provider = request.provider.strip().lower() or "openai"
        cached = self._program_cache.get(provider)
        if cached is not None:
            return cached
        result = load_program(settings=self._settings or get_settings(), provider_name=provider)
        cached = (result.program, result.warnings)
        self._program_cache[provider] = cached
        return cached

    def _retrieve(self, post: PostContext, queries: Sequence[str]) -> RetrievalOutput:
        retrieve_result = getattr(self._retriever, "retrieve_result", None)
        if callable(retrieve_result):
            if _accepts_queries(retrieve_result):
                return retrieve_result(post, queries)
            return retrieve_result(post)
        retrieve = self._retriever.retrieve
        if _accepts_queries(retrieve):
            return retrieve(post, queries)
        return retrieve(post)

    def _retrieve_with_optional_adaptive(
        self,
        post: PostContext,
        plan: QueryPlan,
        *,
        allow_adaptive: bool = True,
    ) -> tuple[EvidenceBundle, list[str], list[str]]:
        first_queries = list(plan.queries)
        first = normalize_retrieval_output(
            self._retrieve(post, first_queries),
            retriever=self._retriever,
        )
        should_adapt, preliminary_score = should_run_adaptive_round(post, first)
        if not should_adapt:
            return first, [], first_queries
        if not allow_adaptive:
            return first, ["adaptive_retrieval_skipped_prompt_injection_risk"], first_queries

        second_queries = adaptive_runtime_queries(post, plan.category, first_queries)
        if not second_queries:
            return (
                first,
                [f"adaptive_retrieval_cut_no_safe_query:{preliminary_score:.3f}"],
                first_queries,
            )

        second = normalize_retrieval_output(
            self._retrieve(post, second_queries),
            retriever=self._retriever,
        )
        merged = merge_bundles(first, second)
        trace_queries = _dedupe([*first_queries, *second_queries])
        return merged, [f"adaptive_retrieval_round_2:{preliminary_score:.3f}"], trace_queries

    def _plan_queries(
        self,
        program: BlueskyExplainer,
        post: PostContext,
        pre_retrieval_flags: Sequence[str],
    ) -> tuple[QueryPlan, list[str]]:
        if "prompt_injection_risk" in pre_retrieval_flags:
            return QueryPlan(
                category="guarded_context",
                queries=[_safe_post_query(post)],
            ), ["query_generation_skipped_prompt_injection_risk"]
        plan = program.plan_queries(post, reset_trace=False)
        queries = runtime_queries(post, plan.category, plan.queries)
        return QueryPlan(category=plan.category, queries=queries), []


def build_agent_explainer_service(
    *,
    fetcher: PostContextFetcher,
    retriever: EvidenceRetriever,
    settings: Settings | None = None,
    prefer_dspy: bool = True,
    extra_warnings: Sequence[str] = (),
    provider_aware: bool = True,
) -> AgentExplainerService:
    """Build the runtime explainer service for route wiring."""

    if provider_aware:
        if not prefer_dspy:
            program_result = load_program(settings=settings, prefer_dspy=False)
            return AgentExplainerService(
                fetcher=fetcher,
                retriever=retriever,
                program=program_result.program,
                settings=settings,
                extra_warnings=[*program_result.warnings, *extra_warnings],
            )
        return AgentExplainerService(
            fetcher=fetcher,
            retriever=retriever,
            settings=settings,
            extra_warnings=extra_warnings,
        )

    program_result = load_program(settings=settings, prefer_dspy=prefer_dspy)
    return AgentExplainerService(
        fetcher=fetcher,
        retriever=retriever,
        program=program_result.program,
        settings=settings,
        extra_warnings=[*program_result.warnings, *extra_warnings],
    )


def _accepts_queries(retrieve: Any) -> bool:
    params = list(signature(retrieve).parameters.values())
    if any(param.kind is Parameter.VAR_POSITIONAL for param in params):
        return True
    positional = [
        param
        for param in params
        if param.kind in {Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD}
    ]
    return len(positional) >= 2


def _safe_post_query(post: PostContext) -> str:
    author = post.author.strip() or "unknown-author"
    return f"{author} Bluesky post context"


def _retrieval_warning_flags(warnings: Sequence[str]) -> list[str]:
    prefixes = ("rag_runtime_failed:", "retrieval_adapter_failed:", "retrieval_failed:")
    if any(warning.startswith(prefixes) for warning in warnings):
        return ["retrieval_unavailable"]
    return []


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped
