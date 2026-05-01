from __future__ import annotations

import sys
import types
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.clients.bsky import BlueskyClient
from app.config import Settings
from app.deps import build_gate3_explainer
from app.ml import retrieval_service
from app.ml.embeddings import DeterministicHashEmbeddingProvider
from app.ml.vector_store import InMemoryVectorStore
from app.schemas.api import ExplainRequest, ExplainResponse
from app.schemas.domain import PostContext

GATE5_C1_URL = "https://bsky.app/profile/example.com/post/3gate5c1"


@dataclass
class ResolveResponse:
    did: str


class Gate5C1AtprotoClient:
    """Cached public-read shaped fixture for the Dev A -> Dev B handoff."""

    def resolve_handle(self, handle: str) -> ResolveResponse:
        assert handle == "example.com"
        return ResolveResponse(did="did:plc:gate5target")

    def get_post_thread(self, uri: str, depth: int, parent_height: int) -> dict[str, object]:
        assert uri == "at://did:plc:gate5target/app.bsky.feed.post/3gate5c1"
        assert depth == 3
        assert parent_height == 2
        return {"thread": {"post": _target_post(uri), "parent": _parent_thread()}}


def _target_post(uri: str) -> dict[str, object]:
    return {
        "uri": uri,
        "cid": "target-cid",
        "indexed_at": "2026-04-30T10:00:10Z",
        "author": {
            "did": "did:plc:gate5target",
            "handle": "example.com",
            "display_name": "Example Author",
        },
        "record": _target_record(),
        "embed": _target_embed(),
    }


def _target_record() -> dict[str, object]:
    return {
        "text": "Target post asks why a quoted project update is trending.",
        "created_at": "2026-04-30T10:00:00Z",
        "langs": ["en"],
        "reply": {
            "root": {"uri": "at://did:plc:root/app.bsky.feed.post/3root"},
            "parent": {"uri": "at://did:plc:parent/app.bsky.feed.post/3parent"},
        },
        "facets": [{"features": [{"uri": "https://example.com/background-report"}]}],
    }


def _target_embed() -> dict[str, object]:
    return {
        "record": {
            "record": {
                "uri": "at://did:plc:quote/app.bsky.feed.post/3quote",
                "cid": "quote-cid",
                "author": {"did": "did:plc:quote", "handle": "quote.example"},
                "value": {
                    "text": "Quoted project update with the original claim.",
                    "created_at": "2026-04-30T09:45:00Z",
                },
            }
        },
        "media": {
            "external": {
                "uri": "https://example.com/embedded-context",
                "title": "Embedded context",
                "description": "Background context for the quote.",
                "thumb": "https://cdn.example.com/link-thumb.jpg",
            },
            "images": [
                {
                    "thumb": "https://cdn.example.com/image-thumb.jpg",
                    "fullsize": "https://cdn.example.com/image-full.jpg",
                    "alt": "Screenshot of the project update.",
                }
            ],
        },
    }


def _parent_thread() -> dict[str, object]:
    return {
        "post": {
            "uri": "at://did:plc:parent/app.bsky.feed.post/3parent",
            "author": {"did": "did:plc:parent", "handle": "parent.example"},
            "record": {
                "text": "Parent reply asks for context about the update.",
                "created_at": "2026-04-30T09:59:00Z",
            },
        },
        "parent": {"$type": "app.bsky.feed.defs#blockedPost", "blocked": True},
    }


def build_gate5_c1_post_context_fixture() -> PostContext:
    """Return the cached C1 handoff object without network or schema adapters."""

    return BlueskyClient(client=Gate5C1AtprotoClient()).fetch_context(GATE5_C1_URL)


def test_gate5_route_wiring_uses_dev_c_builder_and_dev_b_retrieval_queries(
    monkeypatch: Any,
) -> None:
    import app.agent.service as agent_service

    captured: dict[str, object] = {}
    expected_service = object()

    class FakeRetrievalService:
        async def retrieve(
            self,
            post: PostContext,
            queries: Sequence[str] | None = None,
        ) -> dict[str, object]:
            captured.update(retrieval_post=post, queries=list(queries or []))
            return {"evidence": [], "documents": [], "warnings": ["retrieval_warning"]}

    def build_retrieval_service(*, settings: object) -> FakeRetrievalService:
        captured["retrieval_settings"] = settings
        return FakeRetrievalService()

    def build_agent_explainer_service(
        *,
        fetcher: object,
        retriever: Any,
        settings: object,
    ) -> object:
        captured["fetcher"] = fetcher
        captured["agent_settings"] = settings
        post = PostContext(
            url="https://bsky.app/profile/example.com/post/3abcxyz",
            at_uri="at://did:plc:example/app.bsky.feed.post/3abcxyz",
            author="example.com",
            text="Post text",
            created_at=datetime(2026, 4, 29, tzinfo=UTC),
        )
        captured["retrieval_result"] = retriever.retrieve(post, queries=["planned query"])
        return expected_service

    retrieval_module = types.ModuleType("app.ml.retrieval_service")
    retrieval_module.build_retrieval_service = build_retrieval_service  # type: ignore[attr-defined]
    adapter_module = types.ModuleType("app.ml.retrieval_adapter")
    monkeypatch.setitem(sys.modules, "app.ml.retrieval_adapter", adapter_module)
    monkeypatch.setitem(sys.modules, "app.ml.retrieval_service", retrieval_module)
    builder = build_agent_explainer_service
    monkeypatch.setattr(agent_service, "build_agent_explainer_service", builder)

    service = build_gate3_explainer(bluesky_client=BlueskyClient(client=Gate5C1AtprotoClient()))

    assert service is expected_service
    assert isinstance(captured["fetcher"], BlueskyClient)
    assert captured["retrieval_settings"] is captured["agent_settings"]
    assert captured["queries"] == ["planned query"]
    assert captured["retrieval_result"] == {
        "evidence": [],
        "documents": [],
        "warnings": ["retrieval_warning"],
    }


def test_gate5_c1_post_context_fixture_contains_dev_b_handoff_fields() -> None:
    context = build_gate5_c1_post_context_fixture()

    assert context.url == GATE5_C1_URL
    assert context.at_uri == "at://did:plc:gate5target/app.bsky.feed.post/3gate5c1"
    assert context.author == "example.com"
    assert context.metadata["resolved_did"] == "did:plc:gate5target"
    assert context.metadata["reply_parent_at_uri"] == (
        "at://did:plc:parent/app.bsky.feed.post/3parent"
    )
    assert context.parent_texts == ["Parent reply asks for context about the update."]
    assert context.parent_posts[0].at_uri == "at://did:plc:parent/app.bsky.feed.post/3parent"
    assert context.parent_posts[0].author == "parent.example"
    assert context.quoted_texts == ["Quoted project update with the original claim."]
    assert context.quoted_posts[0].at_uri == "at://did:plc:quote/app.bsky.feed.post/3quote"
    assert context.quoted_posts[0].author == "quote.example"
    assert context.quoted_posts[0].created_at is not None
    assert context.quoted_posts[0].created_at.isoformat() == "2026-04-30T09:45:00+00:00"
    assert context.quoted_posts[0].metadata["cid"] == "quote-cid"
    assert context.links == [
        "https://example.com/background-report",
        "https://example.com/embedded-context",
    ]
    assert context.external_links[1].title == "Embedded context"
    assert context.images[0].url == "https://cdn.example.com/image-full.jpg"
    assert context.images[0].thumb_url == "https://cdn.example.com/image-thumb.jpg"
    assert context.images[0].fullsize_url == "https://cdn.example.com/image-full.jpg"
    assert context.images[0].alt_text == "Screenshot of the project update."
    assert context.warnings == ["Parent Bluesky post is blocked."]

    payload = context.model_dump(mode="json")
    assert PostContext.model_validate(payload) == context


def test_gate5_c5_dependency_builder_composes_dev_a_dev_b_and_dev_c(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        retrieval_service,
        "OpenAIEmbeddingProvider",
        lambda *, settings: DeterministicHashEmbeddingProvider(),
    )
    monkeypatch.setattr(
        retrieval_service,
        "_vector_store_or_fallback",
        lambda settings, vector_store: (InMemoryVectorStore(), []),
    )
    monkeypatch.setattr(
        retrieval_service,
        "_default_search_providers",
        lambda settings, fetcher: [],
    )
    post_context = build_gate5_c1_post_context_fixture()
    service = build_gate3_explainer(
        bluesky_client=BlueskyClient(client=Gate5C1AtprotoClient()),
        settings=Settings(),
    )

    response = service.explain(ExplainRequest(post_url=post_context.url, provider="openai"))

    assert isinstance(ExplainResponse.model_validate(response.model_dump()), ExplainResponse)
    assert type(service).__name__ == "AgentExplainerService"
    assert type(service._retriever).__name__ == "RetrievalEvidenceRetriever"  # noqa: SLF001
    assert response.trace.queries
    assert "search_rag_not_connected_using_thread_context_evidence" not in response.trace.warnings
    assert "Parent Bluesky post is blocked." in response.trace.warnings
    assert any(source.type == "thread" for source in response.sources)
