"""Bounded concurrent collection helpers for retrieval context."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any, TypeVar, cast

from app.clients import search as sc
from app.clients.extraction import redact_url_for_warning
from app.clients.fetcher import LinkedPageFetcher
from app.ml import diagnostics as d
from app.ml.boundary import boundary_text, safe_limit
from app.ml.embeddings import text_hash
from app.schemas.domain import ContextDocument

T = TypeVar("T")


async def collect_linked_page_documents(
    links: object,
    *,
    fetcher: LinkedPageFetcher,
    limit: int,
    concurrency: int,
    timeout_seconds: float | None,
) -> tuple[list[ContextDocument], list[str], list[str]]:
    documents: list[ContextDocument] = []
    warnings: list[str] = []
    private_url_blocks: list[str] = []
    link_limit = safe_limit(limit)
    unique_links, overflow_count, link_iter_warnings = d.dedupe_limited_values_with_warnings(
        links, link_limit, "linked_page_iter_failed"
    )
    warnings.extend(link_iter_warnings)
    if overflow_count:
        warnings.append(f"linked_page_limit_exceeded:{overflow_count}")
    semaphore = asyncio.Semaphore(max(1, safe_limit(concurrency) or 1))

    async def fetch_one(index: int, url: object) -> tuple[int, object, Any]:
        async with semaphore:
            result = await fetcher.fetch(
                url,
                source_id=f"LINK-{text_hash(boundary_text(url, 'link_url_text_failed'))[:12]}",
            )
        return index, url, result

    tasks = [
        asyncio.create_task(fetch_one(index, url))
        for index, url in enumerate(unique_links[:link_limit], start=1)
    ]
    completed, timeout_warnings = await ordered_task_results(
        tasks,
        timeout_seconds=timeout_seconds,
        timeout_label="linked_pages",
    )
    warnings.extend(timeout_warnings)
    for index, url, result in completed:
        warnings.extend(result.warnings)
        if result.blocked:
            block = f"blocked_link:{redact_url_for_warning(url)}:{'|'.join(result.warnings)}"
            private_url_blocks.append(block)
            warnings.append(block)
        if result.document is None:
            continue
        metadata = {
            **result.document.metadata,
            "post_link_rank": index,
            "linked_from_post": True,
        }
        documents.append(result.document.model_copy(update={"metadata": metadata}))
    return documents, warnings, private_url_blocks


async def collect_search_documents(
    queries: Sequence[str],
    providers: list[sc.SearchProvider],
    *,
    limit_per_provider: int,
    concurrency: int,
    timeout_seconds: float | None,
) -> tuple[list[ContextDocument], list[str]]:
    documents: list[ContextDocument] = []
    warnings: list[str] = []
    semaphore = asyncio.Semaphore(max(1, safe_limit(concurrency) or 1))

    async def search_one(index: int, query: str) -> tuple[int, sc.SearchBundle]:
        async with semaphore:
            bundle = await sc.collect_search_context(
                query,
                providers,
                limit_per_provider=limit_per_provider,
                concurrency_limit=concurrency,
            )
        return index, bundle

    tasks = [
        asyncio.create_task(search_one(index, query))
        for index, query in enumerate(queries, start=1)
    ]
    completed, timeout_warnings = await ordered_task_results(
        tasks,
        timeout_seconds=timeout_seconds,
        timeout_label="search",
    )
    warnings.extend(timeout_warnings)
    for _index, bundle in completed:
        documents.extend(bundle.documents)
        warnings.extend(bundle.warnings)
    return documents, warnings


async def ordered_task_results(
    tasks: Sequence[asyncio.Task[T]],
    *,
    timeout_seconds: float | None,
    timeout_label: str,
) -> tuple[list[T], list[str]]:
    if not tasks:
        return [], []
    if timeout_seconds is not None and timeout_seconds <= 0:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        return [], [f"retrieval_partial_results_timeout:{timeout_label}:{len(tasks)}"]
    done, pending = await asyncio.wait(tasks, timeout=timeout_seconds)
    warnings: list[str] = []
    if pending:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        warnings.append(f"retrieval_partial_results_timeout:{timeout_label}:{len(pending)}")
    results = _completed_results(done, timeout_label, warnings)
    return sorted(results, key=lambda item: cast(Any, item)[0]), warnings


def deadline(timeout_seconds: float) -> float | None:
    try:
        timeout_value = float(timeout_seconds)
    except Exception:
        return None
    if timeout_value <= 0:
        return asyncio.get_running_loop().time()
    return asyncio.get_running_loop().time() + timeout_value


def remaining_timeout(active_deadline: float | None) -> float | None:
    if active_deadline is None:
        return None
    return max(0.0, active_deadline - asyncio.get_running_loop().time())


def _completed_results(
    done: set[asyncio.Task[T]],
    timeout_label: str,
    warnings: list[str],
) -> list[T]:
    results: list[T] = []
    for task in done:
        try:
            results.append(task.result())
        except asyncio.CancelledError:
            warnings.append(f"retrieval_partial_results_cancelled:{timeout_label}")
        except Exception as exc:
            warnings.append(
                f"retrieval_partial_results_failed:{timeout_label}:{exc.__class__.__name__}"
            )
    return results
