from __future__ import annotations

from typing import Any, cast

import pytest

from app.clients.search import collect_search_context
from app.ml.boundary import safe_limit
from app.schemas.domain import ContextDocument


class BadLimit:
    def __int__(self) -> int:
        raise RuntimeError("limit failed")


def test_safe_limit_caps_huge_values() -> None:
    assert safe_limit(10**9) == 200


def _document() -> ContextDocument:
    return ContextDocument(
        id="D1",
        source_type="web",
        title="Doc",
        url="https://example.com",
        text="Context",
        metadata={},
    )


@pytest.mark.asyncio
async def test_collect_search_context_treats_bad_limit_as_zero() -> None:
    class BadLimitProvider:
        calls = 0

        async def search(self, query: str, limit: int = 5) -> list[ContextDocument]:
            del query, limit
            self.calls += 1
            return [_document()]

    provider = BadLimitProvider()

    bundle = await collect_search_context(
        "mars rover",
        [provider],
        cast(Any, BadLimit()),
    )

    assert bundle.documents == []
    assert bundle.warnings == []
    assert provider.calls == 0
