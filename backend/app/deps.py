"""FastAPI dependency factories and lightweight service registries."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from contextvars import ContextVar
from importlib import import_module
from inspect import Parameter, signature
from threading import Thread
from typing import Any, cast

from app.agent.loader import load_program
from app.agent.service import AgentExplainerService, ThreadContextFallbackRetriever
from app.clients.bsky import BlueskyClient
from app.config import Settings, get_settings
from app.schemas.domain import ProviderInfo

_post_context_warnings: ContextVar[tuple[str, ...]] = ContextVar(
    "post_context_warnings",
    default=(),
)


def get_provider_catalog(settings: Settings | None = None) -> list[ProviderInfo]:
    """Return provider availability without making network calls."""

    active_settings = settings or get_settings()
    return [
        ProviderInfo(
            name="openai",
            configured=active_settings.openai_api_key is not None,
            skipped_reason=None
            if active_settings.openai_api_key
            else "OPENAI_API_KEY is not configured",
            default_model=active_settings.dspy_model,
        ),
        ProviderInfo(
            name="anthropic",
            configured=active_settings.anthropic_api_key is not None,
            skipped_reason=None
            if active_settings.anthropic_api_key
            else "ANTHROPIC_API_KEY is not configured",
        ),
        ProviderInfo(
            name="gemini",
            configured=active_settings.gemini_api_key is not None,
            skipped_reason=None
            if active_settings.gemini_api_key
            else "GEMINI_API_KEY is not configured",
        ),
        ProviderInfo(
            name="ollama",
            configured=False,
            skipped_reason="Ollama provider is reserved for T8 provider comparison",
        ),
    ]


class PostContextWarningRetriever:
    """Retriever wrapper that carries Bluesky context warnings into public trace."""

    def __init__(self, retriever: Any) -> None:
        self._retriever = retriever

    @property
    def warnings(self) -> Sequence[str]:
        retriever_warnings = tuple(str(item) for item in getattr(self._retriever, "warnings", ()))
        return (*retriever_warnings, *_post_context_warnings.get())

    def retrieve(self, post: Any, queries: Sequence[str] = ()) -> Any:
        self._record_post_warnings(post)
        retrieve = self._retriever.retrieve
        if _accepts_queries(retrieve):
            return retrieve(post, queries)
        return retrieve(post)

    def retrieve_result(self, post: Any, queries: Sequence[str] = ()) -> Any:
        self._record_post_warnings(post)
        retrieve_result = getattr(self._retriever, "retrieve_result", None)
        if not callable(retrieve_result):
            return self.retrieve(post, queries)
        if _accepts_queries(retrieve_result):
            return retrieve_result(post, queries)
        return retrieve_result(post)

    def _record_post_warnings(self, post: Any) -> None:
        _post_context_warnings.set(tuple(str(warning) for warning in getattr(post, "warnings", ())))


class QueryAwareRetrievalRetriever:
    """Sync route adapter for retrieval that preserves planned query intent."""

    def __init__(self, retrieval_service: Any) -> None:
        self._retrieval_service = retrieval_service

    def retrieve(self, post: Any, queries: Sequence[str] = ()) -> Any:
        result = self._retrieval_service.retrieve(post, queries=queries)
        if hasattr(result, "__await__"):
            return _run_awaitable_sync(result)
        return result


def build_current_explainer(
    bluesky_client: Any | None = None,
    retriever: Any | None = None,
    program: Any | None = None,
    settings: Settings | None = None,
) -> AgentExplainerService:
    """Build the current explain service.

    The default route path uses real Bluesky fetching, Search/RAG retrieval,
    and the agent service when those modules are present. Thread-context
    evidence remains only the explicit fallback or injected test path, and any
    fallback warnings stay visible in trace output.
    """

    active_settings = settings or get_settings()
    if retriever is None and program is None:
        runtime_service = _build_runtime_explainer(bluesky_client, active_settings)
        if runtime_service is not None:
            return cast(AgentExplainerService, runtime_service)
    extra_warnings: Sequence[str] = ()
    active_program = program
    if active_program is None:
        program_result = load_program(settings=active_settings)
        active_program = program_result.program
        extra_warnings = program_result.warnings
    active_retriever = PostContextWarningRetriever(retriever or ThreadContextFallbackRetriever())
    return AgentExplainerService(
        fetcher=bluesky_client or BlueskyClient(),
        retriever=active_retriever,
        program=active_program,
        extra_warnings=extra_warnings,
    )


def build_gate3_explainer(
    bluesky_client: Any | None = None,
    retriever: Any | None = None,
    program: Any | None = None,
    settings: Settings | None = None,
) -> AgentExplainerService:
    """Backward-compatible alias for older tests and review docs."""

    return build_current_explainer(
        bluesky_client=bluesky_client,
        retriever=retriever,
        program=program,
        settings=settings,
    )


def _build_runtime_explainer(bluesky_client: Any | None, settings: Settings) -> Any | None:
    try:
        agent_service = import_module("app.agent.service")
        retrieval_adapter = import_module("app.ml.retrieval_adapter")
        retrieval_service = import_module("app.ml.retrieval_service")
    except ImportError:
        return None
    agent_builder = getattr(agent_service, "build_agent_explainer_service", None)
    adapter = getattr(retrieval_adapter, "RetrievalEvidenceRetriever", None)
    retrieval_builder = getattr(retrieval_service, "build_retrieval_service", None)
    if not callable(agent_builder) or not callable(retrieval_builder):
        return None
    active_retrieval_service = _build_runtime_retrieval_service(
        retrieval_service,
        retrieval_builder,
        settings,
    )
    active_retriever = (
        adapter(active_retrieval_service)
        if callable(adapter)
        else QueryAwareRetrievalRetriever(active_retrieval_service)
    )
    return agent_builder(
        fetcher=bluesky_client or BlueskyClient(),
        retriever=active_retriever,
        settings=settings,
    )


def _build_runtime_retrieval_service(
    retrieval_module: Any,
    retrieval_builder: Any,
    settings: Settings,
) -> Any:
    kwargs: dict[str, Any] = {"settings": settings}
    if _accepts_keyword(retrieval_builder, "retrieval_settings"):
        retrieval_settings = _runtime_retrieval_settings(retrieval_module, settings)
        if retrieval_settings is not None:
            kwargs["retrieval_settings"] = retrieval_settings
    return retrieval_builder(**kwargs)


def _runtime_retrieval_settings(retrieval_module: Any, settings: Settings) -> Any | None:
    settings_type = getattr(retrieval_module, "RetrievalSettings", None)
    if not callable(settings_type):
        return None
    try:
        return settings_type(
            max_queries=settings.retrieval_max_queries,
            search_limit_per_provider=settings.retrieval_search_limit_per_provider,
            linked_page_limit=settings.retrieval_linked_page_limit,
            linked_page_concurrency=settings.retrieval_linked_page_concurrency,
            search_concurrency=settings.retrieval_search_concurrency,
            retrieval_timeout_seconds=settings.retrieval_timeout_seconds,
        )
    except TypeError:
        return settings_type()


def _run_awaitable_sync(awaitable: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    return _run_awaitable_in_thread(awaitable)


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


def _accepts_keyword(callable_obj: Any, keyword: str) -> bool:
    try:
        params = signature(callable_obj).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        param.kind is Parameter.VAR_KEYWORD
        or (
            param.kind in {Parameter.KEYWORD_ONLY, Parameter.POSITIONAL_OR_KEYWORD}
            and param.name == keyword
        )
        for param in params
    )


def _run_awaitable_in_thread(awaitable: Any) -> Any:
    values: list[Any] = []
    errors: list[BaseException] = []

    def runner() -> None:
        try:
            values.append(asyncio.run(awaitable))
        except BaseException as exc:
            errors.append(exc)

    thread = Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    if not values:
        raise RuntimeError("retrieval service did not return a result")
    return values[0]
