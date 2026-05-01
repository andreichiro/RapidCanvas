"""Route-compatible service wrapper for the Dev C agent program."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from inspect import Parameter, signature
from typing import Any, Protocol

from app.agent.evidence_contract import RetrievalOutput, normalize_retrieval_output
from app.agent.loader import load_program
from app.agent.program import BlueskyExplainer
from app.agent.quality_trace import AgentQualityTrace
from app.agent.runner import QueryPlan
from app.config import Settings, get_settings
from app.schemas.api import ExplainRequest, ExplainResponse
from app.schemas.domain import ContextDocument, Evidence, PostContext


@dataclass(frozen=True)
class StaticEvidenceRetriever:
    """Test helper retriever for FastAPI service integration tests."""

    evidence: Sequence[Evidence] = field(default_factory=list)
    documents: Sequence[ContextDocument] = field(default_factory=list)
    warnings: Sequence[str] = field(default_factory=list)

    def retrieve(
        self,
        post: PostContext,
        queries: Sequence[str] = (),
    ) -> tuple[Sequence[Evidence], Sequence[ContextDocument]]:
        del post, queries
        return self.evidence, self.documents


class ThreadContextEvidenceRetriever:
    """Temporary Dev C retriever using normalized Bluesky thread context as evidence."""

    warnings: Sequence[str] = (
        "search_rag_not_connected_using_thread_context_evidence",
        "dev_c_api_path_uses_agent_guardrails",
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
    """Protocol for Dev A's Bluesky client without importing the client module."""

    def fetch_context(self, url: str) -> PostContext:
        """Fetch a normalized public post context."""


class EvidenceRetriever(Protocol):
    """Protocol for Dev B retrieval without coupling to client modules."""

    @property
    def warnings(self) -> Sequence[str]:
        """Non-fatal retrieval warnings for trace output."""

    def retrieve(self, post: PostContext, queries: Sequence[str] = ()) -> RetrievalOutput:
        """Retrieve evidence and source documents for a post."""


class AgentExplainerService:
    """Route-compatible service that wires fetch, retrieval, and the Dev C program."""

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
        bundle = normalize_retrieval_output(
            self._retrieve(post, plan.queries),
            retriever=self._retriever,
        )
        warnings = _dedupe(
            [
                *post.warnings,
                *bundle.warnings,
                *bundle.source_safety_diagnostics,
                *program_warnings,
                *plan_warnings,
                *self._extra_warnings,
            ]
        )
        response = program.explain_context(
            post=post,
            evidence=bundle.evidence,
            documents=bundle.documents,
            request=request,
            warnings=warnings,
            retrieval_guardrail_flags=bundle.guardrail_flags,
            pre_retrieval_guardrail_flags=pre_retrieval_flags,
            planned_category=plan.category,
            planned_queries=plan.queries,
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
        retrieve = self._retriever.retrieve
        if _accepts_queries(retrieve):
            return retrieve(post, queries)
        return retrieve(post)

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
        return program.plan_queries(post, reset_trace=False), []


def build_agent_explainer_service(
    *,
    fetcher: PostContextFetcher,
    retriever: EvidenceRetriever,
    settings: Settings | None = None,
    prefer_dspy: bool = True,
    extra_warnings: Sequence[str] = (),
    provider_aware: bool = True,
) -> AgentExplainerService:
    """Build the Dev C C3 service for Dev A route wiring."""

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


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped
