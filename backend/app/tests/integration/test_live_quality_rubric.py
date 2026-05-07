from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest

from app.agent.sources import sources_for_response
from app.clients.fetcher import FetchResult
from app.clients.search import SearchBundle
from app.ml.embeddings import normalize_vector
from app.ml.rerankers import SimilarityReranker
from app.ml.retrieval_service import RetrievalService, RetrievalSettings
from app.ml.vector_store import ChunkingConfig, InMemoryVectorStore, RagService
from app.schemas.domain import ContextDocument, PostContext


class RubricEmbeddingProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [
            normalize_vector(
                [
                    float(text.lower().count("ichiro")),
                    float(text.lower().count("quote")),
                    float(text.lower().count("mariners")),
                    float(text.lower().count("ceremony")),
                    float(text.lower().count("catalog")),
                ]
            )
            for text in texts
        ]


class PrimaryLinkFetcher:
    @property
    def resolver(self) -> Any:
        return lambda hostname: ("93.184.216.34",)

    async def fetch(self, url: object, source_id: str | None = None) -> FetchResult:
        assert url == "https://www.mlb.com/mariners/news/ichiro-ceremony-quote"
        return FetchResult(
            document=ContextDocument(
                id=source_id or "PRIMARY",
                source_type="web",
                title="Mariners ceremony transcript",
                url=str(url),
                text=(
                    "The Mariners published Ichiro's ceremony quote and explained the "
                    "context from the team event."
                ),
                metadata={
                    "provider": "linked_page",
                    "canonical_domain": "mlb.com",
                    "fetch_success": True,
                    "fetch_status": 200,
                    "extracted_length": 126,
                },
            ),
            status_code=200,
        )


class RubricSearchProvider:
    async def search_with_warnings(self, query: str, limit: int = 5) -> SearchBundle:
        del query, limit
        return SearchBundle(
            documents=[
                ContextDocument(
                    id="CARD",
                    source_type="web",
                    title="Ichiro Suzuki trading card catalog",
                    url="https://www.tcdb.com/ViewCard.cfm/sid/1/cid/2/Ichiro-Suzuki",
                    text=(
                        "Ichiro quote Mariners ceremony catalog marketplace trading card "
                        "checklist price guide buy sell coupon."
                    ),
                    metadata={
                        "provider": "web_search",
                        "query": "ichiro quote mariners ceremony",
                        "rank": 1,
                        "domain": "tcdb.com",
                        "fetch_success": True,
                        "fetch_status": 200,
                    },
                ),
                ContextDocument(
                    id="SNIP",
                    source_type="web",
                    title="Search snippet about Ichiro ceremony",
                    url="https://example.com/search-snippet",
                    text="Search result snippet: Ichiro Mariners ceremony quote.",
                    metadata={
                        "provider": "web_search",
                        "query": "ichiro quote mariners ceremony",
                        "rank": 2,
                        "domain": "example.com",
                        "snippet_only": True,
                        "fetch_success": False,
                        "fetch_status": 404,
                    },
                ),
            ],
            warnings=[],
        )


def _post() -> PostContext:
    return PostContext(
        url="https://bsky.app/profile/sportswriter.example/post/3abc",
        at_uri="at://did:plc:sports/app.bsky.feed.post/3abc",
        author="sportswriter.example",
        text="That Ichiro quote after the Mariners ceremony was perfect.",
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        links=["https://www.mlb.com/mariners/news/ichiro-ceremony-quote"],
    )


@pytest.mark.asyncio
async def test_live_quality_rubric_prefers_primary_source_and_blocks_catalog_citation() -> None:
    service = RetrievalService(
        rag_service=RagService(
            embedding_provider=RubricEmbeddingProvider(),
            vector_store=InMemoryVectorStore(),
            reranker=SimilarityReranker(),
            chunking=ChunkingConfig(name="test", size=260, overlap=20),
            retrieve_limit=6,
            evidence_limit=4,
        ),
        search_providers=[cast(Any, RubricSearchProvider())],
        linked_page_fetcher=cast(Any, PrimaryLinkFetcher()),
        settings=RetrievalSettings(
            include_thread_context=False,
            include_linked_pages=True,
            include_search=True,
            linked_page_limit=1,
            search_limit_per_provider=2,
            retrieve_limit=6,
            evidence_limit=4,
        ),
    )

    result = await service.retrieve(_post(), queries=["ichiro quote mariners ceremony"])
    quality_by_id = {row["id"]: row for row in result.diagnostics.source_quality}
    sources = sources_for_response(_post(), result.evidence, result.documents)

    assert quality_by_id["CARD"]["citation_eligible"] is False
    assert quality_by_id["SNIP"]["citation_eligible"] is False
    assert any(
        row["citation_eligible"] is True and row["source_type"] == "web"
        for row in result.diagnostics.source_quality
    )
    assert result.evidence[0].document_id != "CARD"
    assert "CARD" not in {source.id for source in sources}
    assert "SNIP" not in {source.id for source in sources}
