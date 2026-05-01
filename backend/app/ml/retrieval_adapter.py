"""Consumer-facing adapter for the Dev B retrieval checkpoint."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Sequence
from contextvars import ContextVar
from threading import Thread
from typing import Any, TypeVar

from app.ml import diagnostics as d
from app.ml.diagnostics import RetrievalDiagnostics, RetrievalResult
from app.ml.retrieval_service import RetrievalService, RetrievalSettings
from app.schemas.domain import ContextDocument, Evidence, PostContext

T = TypeVar("T")


class RetrievalEvidenceRetriever:
    def __init__(
        self,
        service: RetrievalService,
        *,
        queries: Sequence[str] | None = None,
        settings: RetrievalSettings | None = None,
    ) -> None:
        self._service = service
        self._queries = queries
        self._settings = settings
        self._last_result: RetrievalResult | None = None
        self._context_result: ContextVar[RetrievalResult | None] = ContextVar(
            f"retrieval_result:{id(self)}",
            default=None,
        )

    @property
    def warnings(self) -> Sequence[str]:
        result = self._current_result()
        return () if result is None else tuple(result.warnings)

    @property
    def guardrail_flags(self) -> Sequence[str]:
        result = self._current_result()
        return () if result is None else tuple(result.guardrail_flags)

    @property
    def diagnostics(self) -> RetrievalDiagnostics | None:
        result = self._current_result()
        return None if result is None else result.diagnostics

    @property
    def last_result(self) -> RetrievalResult | None:
        return self._current_result()

    def retrieve(
        self,
        post: PostContext,
        queries: Sequence[str] | None = None,
    ) -> tuple[Sequence[Evidence], Sequence[ContextDocument]]:
        result = self.retrieve_result(post, queries=queries)
        return result.evidence, result.documents

    def retrieve_result(
        self,
        post: PostContext,
        queries: Sequence[str] | None = None,
    ) -> RetrievalResult:
        result = _run_coroutine_sync(self._retrieve_result(post, queries=queries))
        self._record_result(result)
        return result

    async def retrieve_result_async(
        self,
        post: PostContext,
        queries: Sequence[str] | None = None,
    ) -> RetrievalResult:
        result = await self._retrieve_result(post, queries=queries)
        self._record_result(result)
        return result

    async def _retrieve_result(
        self,
        post: PostContext,
        queries: Sequence[str] | None = None,
    ) -> RetrievalResult:
        active_queries = self._queries if queries is None else queries
        try:
            return await self._service.retrieve(
                post,
                queries=active_queries,
                settings=self._settings,
            )
        except Exception as exc:
            return d.make_retrieval_result(
                documents=[],
                evidence=[],
                queries=[],
                prompt_flags=[],
                warnings=[f"retrieval_adapter_failed:{exc.__class__.__name__}"],
                private_url_blocks=[],
                extra_guardrail_flags=["retrieval_unavailable"],
            )

    def _record_result(self, result: RetrievalResult) -> None:
        self._last_result = result
        self._context_result.set(result)

    def _current_result(self) -> RetrievalResult | None:
        return self._context_result.get() or self._last_result


def _run_coroutine_sync(coro: Coroutine[Any, Any, T]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return _run_coroutine_in_thread(coro)


def _run_coroutine_in_thread(coro: Coroutine[Any, Any, T]) -> T:
    values: list[T] = []
    errors: list[BaseException] = []

    def runner() -> None:
        try:
            values.append(asyncio.run(coro))
        except BaseException as exc:
            errors.append(exc)

    thread = Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    if not values:
        raise RuntimeError("retrieval adapter did not return a result")
    return values[0]
