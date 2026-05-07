from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from app.ml.retrieval_service import RetrievalService, RetrievalSettings
from app.schemas.domain import ContextDocument, Evidence, PostContext


class RagMissesLinkedPrimary:
    last_diagnostics = None

    def retrieve(self, query: str, documents: list[ContextDocument]) -> list[Evidence]:
        del query
        target = next(document for document in documents if document.id == "POST-target")
        return [
            Evidence(
                id="E1",
                document_id=target.id,
                source_id=target.id,
                text=target.text,
                score=0.66,
            )
        ]


class PrimaryLinkedPageFetcher:
    def resolver(self, hostname: str) -> Sequence[str]:
        del hostname
        return ("93.184.216.34",)

    async def fetch(self, url: object, source_id: str | None = None) -> Any:
        return type(
            "FetchResult",
            (),
            {
                "document": ContextDocument(
                    id=source_id or "LINK-primary",
                    source_type="web",
                    title="Research Example announces AT Protocol moderation tooling",
                    url=str(url),
                    text=(
                        "Research Example announced AT Protocol moderation tooling for "
                        "Bluesky safety labels, review workflows, and implementation details."
                    ),
                    metadata={
                        "fetch_success": True,
                        "fetch_status": 200,
                        "extracted_length": 160,
                    },
                ),
                "warnings": (),
                "blocked": False,
            },
        )()


@pytest.mark.asyncio
async def test_quality_backfill_preserves_direct_link_when_vector_misses_it() -> None:
    post = PostContext(
        url="https://bsky.app/profile/research.example/post/3abc",
        at_uri="at://did:plc:research/app.bsky.feed.post/3abc",
        author="research.example",
        text="Research Example announced AT Protocol moderation tooling.",
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        links=["https://research.example/blog/atproto-moderation-tooling"],
    )
    service = RetrievalService(
        rag_service=cast(Any, RagMissesLinkedPrimary()),
        search_providers=[],
        linked_page_fetcher=cast(Any, PrimaryLinkedPageFetcher()),
        settings=RetrievalSettings(
            include_search=False,
            include_bluesky_search=False,
            include_web_search=False,
            evidence_limit=4,
        ),
    )

    result = await service.retrieve(post, queries=["AT Protocol moderation tooling"])

    assert any(item.source_id.startswith("LINK-") for item in result.evidence)
    linked = next(document for document in result.documents if document.id.startswith("LINK-"))
    assert linked.metadata["citation_eligible"] is True
    assert linked.metadata["citation_role"] == "primary"
