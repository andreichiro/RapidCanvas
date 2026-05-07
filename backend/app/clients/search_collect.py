"""Bounded concurrent search-provider orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from app.clients import search_support as ss
from app.ml.boundary import boundary_text, bounded_items, safe_limit
from app.schemas.domain import ContextDocument

_LEGACY_PROVIDER_LOCKS: dict[int, asyncio.Lock] = {}


class SearchProvider(Protocol):
    async def search(self, query: str, limit: int = 5) -> list[ContextDocument]: ...


@dataclass(frozen=True)
class SearchBundle:
    documents: list[ContextDocument]
    warnings: list[str]


class SearchProviderWithWarnings(SearchProvider, Protocol):
    async def search_with_warnings(self, query: str, limit: int = 5) -> SearchBundle: ...


@dataclass(frozen=True)
class _ProviderBundle:
    index: int
    provider: SearchProvider
    bundle: SearchBundle


async def collect_search_context(
    query: str,
    providers: Sequence[SearchProvider],
    limit_per_provider: int = 5,
    concurrency_limit: int = 4,
) -> SearchBundle:
    provider_limit = safe_limit(limit_per_provider)
    query_text = boundary_text(query, "search_query_text_failed")
    if provider_limit == 0 or not query_text.strip():
        return SearchBundle(documents=[], warnings=[])
    provider_items, provider_warnings = bounded_items(providers, 50, "search_providers_iter_failed")
    bundles = await _provider_bundles(
        query_text,
        provider_items,
        limit_per_provider=provider_limit,
        concurrency_limit=concurrency_limit,
    )
    documents, warnings = _merge_provider_bundles(
        bundles,
        provider_warnings=provider_warnings,
        limit_per_provider=provider_limit,
    )
    return SearchBundle(documents=documents, warnings=warnings)


async def _provider_bundles(
    query_text: str,
    provider_items: list[object],
    *,
    limit_per_provider: int,
    concurrency_limit: int,
) -> list[_ProviderBundle]:
    semaphore = asyncio.Semaphore(max(1, safe_limit(concurrency_limit) or 1))
    tasks = [
        asyncio.create_task(
            _provider_bundle(
                index,
                provider_item,
                query_text=query_text,
                limit_per_provider=limit_per_provider,
                semaphore=semaphore,
            )
        )
        for index, provider_item in enumerate(provider_items)
    ]
    return sorted(await asyncio.gather(*tasks), key=lambda item: item.index)


async def _provider_bundle(
    index: int,
    provider_item: object,
    *,
    query_text: str,
    limit_per_provider: int,
    semaphore: asyncio.Semaphore,
) -> _ProviderBundle:
    provider = cast(SearchProvider, provider_item)
    async with semaphore:
        try:
            bundle = await _search_provider_bundle(provider, query_text, limit_per_provider)
        except Exception as exc:
            bundle = SearchBundle(
                documents=[], warnings=[ss.provider_failure_warning(provider, exc)]
            )
    return _ProviderBundle(index=index, provider=provider, bundle=bundle)


async def _search_provider_bundle(
    provider: SearchProvider,
    query_text: str,
    limit_per_provider: int,
) -> SearchBundle:
    if callable(getattr(provider, "search_with_warnings", None)):
        return await cast(SearchProviderWithWarnings, provider).search_with_warnings(
            query_text, limit=limit_per_provider
        )
    return await _legacy_provider_search_bundle(provider, query_text, limit_per_provider)


async def _legacy_provider_search_bundle(
    provider: SearchProvider, query: str, limit: int
) -> SearchBundle:
    async with _LEGACY_PROVIDER_LOCKS.setdefault(id(provider), asyncio.Lock()):
        documents = await provider.search(query, limit=limit)
        warnings = ss.warning_strings(getattr(provider, "last_warnings", []))
    return SearchBundle(documents=documents, warnings=warnings)


def _merge_provider_bundles(
    bundles: Sequence[_ProviderBundle],
    *,
    provider_warnings: Sequence[str],
    limit_per_provider: int,
) -> tuple[list[ContextDocument], list[str]]:
    documents: list[ContextDocument] = []
    warnings = list(provider_warnings)
    for provider_bundle in bundles:
        bundle = provider_bundle.bundle
        valid_documents = [doc for doc in bundle.documents if isinstance(doc, ContextDocument)]
        invalid_count = len(bundle.documents) - len(valid_documents)
        overflow_count = max(0, len(valid_documents) - limit_per_provider)
        documents.extend(valid_documents[:limit_per_provider])
        warnings.extend(ss.warning_strings(bundle.warnings))
        name = provider_bundle.provider.__class__.__name__
        if invalid_count:
            warnings.append(f"search_provider_invalid_documents:{name}:{invalid_count}")
        if overflow_count:
            warnings.append(f"search_provider_result_limit_exceeded:{name}:{overflow_count}")
    return documents, warnings
