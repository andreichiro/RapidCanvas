from __future__ import annotations

import asyncio
from time import perf_counter

import pytest

import app.clients.search as search
from app.ml import retrieval_collectors as rc
from app.schemas.domain import ContextDocument


class DelayedProvider:
    active = 0
    max_active = 0

    def __init__(self, name: str, delay: float) -> None:
        self.name = name
        self.delay = delay

    async def search_with_warnings(self, query: str, limit: int = 5) -> search.SearchBundle:
        assert query == "mars rover"
        assert limit == 1
        DelayedProvider.active += 1
        DelayedProvider.max_active = max(DelayedProvider.max_active, DelayedProvider.active)
        try:
            await asyncio.sleep(self.delay)
            return search.SearchBundle([_document(self.name)], [])
        finally:
            DelayedProvider.active -= 1

    async def search(self, query: str, limit: int = 5) -> list[ContextDocument]:
        return (await self.search_with_warnings(query, limit=limit)).documents


@pytest.mark.asyncio
async def test_collect_search_context_runs_providers_concurrently_in_provider_order() -> None:
    DelayedProvider.active = 0
    DelayedProvider.max_active = 0

    started = perf_counter()
    bundle = await search.collect_search_context(
        "mars rover",
        [DelayedProvider("slow", 0.05), DelayedProvider("fast", 0.0)],
        limit_per_provider=1,
        concurrency_limit=2,
    )
    elapsed = perf_counter() - started

    assert elapsed < 0.09
    assert [document.id for document in bundle.documents] == ["slow", "fast"]
    assert DelayedProvider.max_active == 2


@pytest.mark.asyncio
async def test_collect_search_documents_runs_queries_concurrently_in_query_order() -> None:
    provider = QueryDelayedProvider({"slow": 0.05})

    started = perf_counter()
    documents, warnings = await rc.collect_search_documents(
        ["slow", "fast"],
        [provider],
        limit_per_provider=1,
        concurrency=2,
        timeout_seconds=1.0,
    )
    elapsed = perf_counter() - started

    assert elapsed < 0.09
    assert [document.id for document in documents] == ["slow", "fast"]
    assert warnings == ["search_warning:slow", "search_warning:fast"]
    assert provider.max_active == 2


@pytest.mark.asyncio
async def test_collect_search_documents_timeout_keeps_completed_query_results() -> None:
    provider = QueryDelayedProvider({"slow": 0.2})

    documents, warnings = await rc.collect_search_documents(
        ["slow", "fast"],
        [provider],
        limit_per_provider=1,
        concurrency=2,
        timeout_seconds=0.03,
    )

    assert [document.id for document in documents] == ["fast"]
    assert warnings == ["retrieval_partial_results_timeout:search:1", "search_warning:fast"]


class QueryDelayedProvider:
    def __init__(self, delays: dict[str, float]) -> None:
        self._delays = delays
        self._active = 0
        self.max_active = 0

    async def search_with_warnings(self, query: str, limit: int = 5) -> search.SearchBundle:
        assert limit == 1
        self._active += 1
        self.max_active = max(self.max_active, self._active)
        try:
            await asyncio.sleep(self._delays.get(query, 0.0))
            return search.SearchBundle([_document(query)], [f"search_warning:{query}"])
        finally:
            self._active -= 1

    async def search(self, query: str, limit: int = 5) -> list[ContextDocument]:
        return (await self.search_with_warnings(query, limit=limit)).documents


def _document(name: str) -> ContextDocument:
    return ContextDocument(
        id=name,
        source_type="web",
        title=name,
        url=f"https://example.com/{name}",
        text=f"{name} evidence",
    )
