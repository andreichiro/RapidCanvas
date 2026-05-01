from __future__ import annotations

from typing import Any, cast

import pytest

from app.clients.search import (
    BlueskySearchProvider,
    SearchBundle,
    WebSearchProvider,
    collect_search_context,
)
from app.schemas.domain import ContextDocument


class BadString:
    def __str__(self) -> str:
        raise RuntimeError("warning string failed")


def _document(index: int) -> ContextDocument:
    return ContextDocument(
        id=f"D{index}",
        source_type="web",
        title=f"Doc {index}",
        url=f"https://example.com/{index}",
        text=f"Context {index}",
        metadata={},
    )


@pytest.mark.asyncio
async def test_collect_search_context_enforces_provider_limit() -> None:
    class OverLimitProvider:
        async def search(self, query: str, limit: int = 5) -> list[ContextDocument]:
            return (await self.search_with_warnings(query, limit=limit)).documents

        async def search_with_warnings(self, query: str, limit: int = 5) -> SearchBundle:
            assert query == "mars rover"
            assert limit == 1
            return SearchBundle(
                documents=[_document(1), _document(2), _document(3)],
                warnings=["provider_warning"],
            )

    bundle = await collect_search_context("mars rover", [OverLimitProvider()], 1)

    assert [document.id for document in bundle.documents] == ["D1"]
    assert "provider_warning" in bundle.warnings
    assert "search_provider_result_limit_exceeded:OverLimitProvider:2" in bundle.warnings


@pytest.mark.asyncio
async def test_collect_search_context_skips_providers_when_limit_is_non_positive() -> None:
    class NegativeLimitProvider:
        calls = 0

        async def search(self, query: str, limit: int = 5) -> list[ContextDocument]:
            return (await self.search_with_warnings(query, limit=limit)).documents

        async def search_with_warnings(self, query: str, limit: int = 5) -> SearchBundle:
            del query, limit
            self.calls += 1
            return SearchBundle(documents=[_document(1)], warnings=[])

    provider = NegativeLimitProvider()
    negative = await collect_search_context("mars rover", [provider], -5)
    zero = await collect_search_context("mars rover", [provider], 0)

    assert negative.documents == []
    assert negative.warnings == []
    assert zero.documents == []
    assert zero.warnings == []
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_collect_search_context_skips_providers_for_blank_query() -> None:
    class BlankQueryProvider:
        calls = 0

        async def search(self, query: str, limit: int = 5) -> list[ContextDocument]:
            del query, limit
            self.calls += 1
            return [_document(1)]

    provider = BlankQueryProvider()

    bundle = await collect_search_context("   ", [provider], 1)

    assert bundle.documents == []
    assert bundle.warnings == []
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_collect_search_context_treats_string_warnings_as_one_warning() -> None:
    class StringWarningProvider:
        async def search(self, query: str, limit: int = 5) -> list[ContextDocument]:
            return (await self.search_with_warnings(query, limit=limit)).documents

        async def search_with_warnings(self, query: str, limit: int = 5) -> SearchBundle:
            del query, limit
            return SearchBundle(documents=[_document(1)], warnings=cast(Any, "provider_warning"))

    bundle = await collect_search_context("mars rover", [StringWarningProvider()], 1)

    assert bundle.warnings == ["provider_warning"]


@pytest.mark.asyncio
async def test_collect_search_context_decodes_bytes_warnings_as_text() -> None:
    class BytesWarningProvider:
        async def search(self, query: str, limit: int = 5) -> list[ContextDocument]:
            return (await self.search_with_warnings(query, limit=limit)).documents

        async def search_with_warnings(self, query: str, limit: int = 5) -> SearchBundle:
            del query, limit
            return SearchBundle(documents=[_document(1)], warnings=cast(Any, b"bytes_warning"))

    bundle = await collect_search_context("mars rover", [BytesWarningProvider()], 1)

    assert bundle.warnings == ["bytes_warning"]


@pytest.mark.asyncio
async def test_legacy_provider_string_last_warnings_stays_one_warning() -> None:
    class LegacyStringWarningProvider:
        last_warnings = "legacy_provider_warning"

        async def search(self, query: str, limit: int = 5) -> list[ContextDocument]:
            del query, limit
            return [_document(1)]

    bundle = await collect_search_context("mars rover", [LegacyStringWarningProvider()], 1)

    assert bundle.warnings == ["legacy_provider_warning"]


@pytest.mark.asyncio
async def test_provider_warning_boundary_accepts_none_and_scalar_warnings() -> None:
    class OddWarningsProvider:
        async def search(self, query: str, limit: int = 5) -> list[ContextDocument]:
            return (await self.search_with_warnings(query, limit=limit)).documents

        async def search_with_warnings(self, query: str, limit: int = 5) -> SearchBundle:
            del query, limit
            return SearchBundle(documents=[_document(1)], warnings=cast(Any, None))

    class ScalarLegacyProvider:
        last_warnings = 7

        async def search(self, query: str, limit: int = 5) -> list[ContextDocument]:
            del query, limit
            return [_document(2)]

    bundle = await collect_search_context(
        "mars rover",
        [OddWarningsProvider(), ScalarLegacyProvider()],
        1,
    )

    assert [document.id for document in bundle.documents] == ["D1", "D2"]
    assert bundle.warnings == ["7"]


@pytest.mark.asyncio
async def test_provider_warning_boundary_handles_bad_string_coercion() -> None:
    class BadStringWarningProvider:
        async def search(self, query: str, limit: int = 5) -> list[ContextDocument]:
            return (await self.search_with_warnings(query, limit=limit)).documents

        async def search_with_warnings(self, query: str, limit: int = 5) -> SearchBundle:
            del query, limit
            return SearchBundle(documents=[_document(1)], warnings=cast(Any, [BadString()]))

    bundle = await collect_search_context("mars rover", [BadStringWarningProvider()], 1)

    assert bundle.warnings == ["warning_text_failed:RuntimeError"]


@pytest.mark.asyncio
async def test_provider_warning_boundary_treats_mapping_as_one_warning() -> None:
    class MappingWarningProvider:
        async def search(self, query: str, limit: int = 5) -> list[ContextDocument]:
            return (await self.search_with_warnings(query, limit=limit)).documents

        async def search_with_warnings(self, query: str, limit: int = 5) -> SearchBundle:
            del query, limit
            return SearchBundle(
                documents=[_document(1)],
                warnings=cast(Any, {"code": "provider_warning"}),
            )

    bundle = await collect_search_context("mars rover", [MappingWarningProvider()], 1)

    assert [document.id for document in bundle.documents] == ["D1"]
    assert bundle.warnings == ["{'code': 'provider_warning'}"]


@pytest.mark.asyncio
async def test_provider_warning_boundary_handles_raising_iterables() -> None:
    class RaisingWarnings:
        def __iter__(self) -> Any:
            yield "first_warning"
            raise RuntimeError("warning iterator failed")

    class RaisingWarningProvider:
        async def search(self, query: str, limit: int = 5) -> list[ContextDocument]:
            return (await self.search_with_warnings(query, limit=limit)).documents

        async def search_with_warnings(self, query: str, limit: int = 5) -> SearchBundle:
            del query, limit
            return SearchBundle(documents=[_document(1)], warnings=cast(Any, RaisingWarnings()))

    bundle = await collect_search_context("mars rover", [RaisingWarningProvider()], 1)

    assert [document.id for document in bundle.documents] == ["D1"]
    assert bundle.warnings == ["first_warning", "warning_iter_failed:RuntimeError"]


@pytest.mark.asyncio
async def test_provider_warning_boundary_handles_iterator_setup_failures() -> None:
    class SetupFailingWarnings:
        def __iter__(self) -> Any:
            raise RuntimeError("warning setup failed")

    class SetupFailingWarningProvider:
        async def search(self, query: str, limit: int = 5) -> list[ContextDocument]:
            return (await self.search_with_warnings(query, limit=limit)).documents

        async def search_with_warnings(self, query: str, limit: int = 5) -> SearchBundle:
            del query, limit
            return SearchBundle(
                documents=[_document(1)],
                warnings=cast(Any, SetupFailingWarnings()),
            )

    bundle = await collect_search_context("mars rover", [SetupFailingWarningProvider()], 1)

    assert [document.id for document in bundle.documents] == ["D1"]
    assert bundle.warnings == ["warning_iter_failed:RuntimeError"]


@pytest.mark.asyncio
async def test_web_search_provider_skips_malformed_hits() -> None:
    class MalformedHitDDGS:
        def text(self, query: str, max_results: int) -> list[str]:
            del query, max_results
            return ["not-a-search-hit"]

    bundle = await WebSearchProvider(
        ddgs_factory=lambda: MalformedHitDDGS()
    ).search_with_warnings("mars", limit=1)

    assert bundle.documents == []
    assert bundle.warnings == ["web_search_invalid_hit:1"]


@pytest.mark.asyncio
async def test_web_search_provider_does_not_overconsume_ddgs_results() -> None:
    class OverflowingDDGS:
        def __init__(self) -> None:
            self.yielded = 0

        def text(self, query: str, max_results: int) -> Any:
            assert query == "mars"
            assert max_results == 1
            while True:
                self.yielded += 1
                if self.yielded > 1:
                    raise AssertionError("provider consumed past caller limit")
                yield {}

    ddgs = OverflowingDDGS()
    bundle = await WebSearchProvider(ddgs_factory=lambda: ddgs).search_with_warnings(
        "mars",
        limit=1,
    )

    assert ddgs.yielded == 1
    assert bundle.documents == []
    assert bundle.warnings == ["web_search_missing_url:1"]


@pytest.mark.asyncio
async def test_built_in_search_providers_skip_non_positive_limits() -> None:
    class LimitRecordingClient:
        def __init__(self) -> None:
            self.limit: int | None = None

        def search_posts(self, query: str, limit: int) -> list[ContextDocument]:
            del query
            self.limit = limit
            return [_document(1)]

    class LimitRecordingDDGS:
        def __init__(self) -> None:
            self.limit: int | None = None

        def text(self, query: str, max_results: int) -> list[dict[str, str]]:
            del query
            self.limit = max_results
            return [{"title": "Doc", "href": "https://example.com/1", "body": "Context"}]

    client = LimitRecordingClient()
    ddgs = LimitRecordingDDGS()

    bluesky = await BlueskySearchProvider(client=client).search_with_warnings("mars", limit=-4)
    web = await WebSearchProvider(ddgs_factory=lambda: ddgs).search_with_warnings("mars", limit=-4)

    assert client.limit is None
    assert ddgs.limit is None
    assert bluesky.documents == []
    assert web.documents == []
