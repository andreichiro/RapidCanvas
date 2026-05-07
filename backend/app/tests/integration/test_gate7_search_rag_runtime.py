from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from app.agent.program import BlueskyExplainer
from app.agent.runner import HeuristicSignatureRunner
from app.agent.service import AgentExplainerService
from app.clients.bsky import BlueskyClient
from app.clients.fetcher import FetchResult
from app.clients.search import SearchBundle
from app.config import Settings
from app.deps import PostContextWarningRetriever, build_gate3_explainer
from app.main import create_app
from app.ml import diagnostics as d
from app.ml import retrieval_service
from app.ml.embeddings import EmbeddingProvider
from app.ml.vector_store import InMemoryVectorStore
from app.schemas.api import ExplainRequest, ExplainResponse
from app.schemas.domain import ContextDocument, Evidence, PostContext

GATE7_URL = "https://bsky.app/profile/example.com/post/3gate7runtime"


@dataclass
class ResolveResponse:
    did: str


class Gate7AtprotoClient:
    def resolve_handle(self, handle: str) -> ResolveResponse:
        assert handle == "example.com"
        return ResolveResponse(did="did:plc:gate7target")

    def get_post_thread(self, uri: str, depth: int, parent_height: int) -> dict[str, object]:
        assert uri == "at://did:plc:gate7target/app.bsky.feed.post/3gate7runtime"
        assert depth == 3
        assert parent_height == 2
        return {
            "thread": {
                "post": {
                    "uri": uri,
                    "cid": "gate7-cid",
                    "indexed_at": "2026-05-01T13:00:10Z",
                    "author": {
                        "did": "did:plc:gate7target",
                        "handle": "example.com",
                    },
                    "record": {
                        "text": "Gate7 runtime context needs outside source support.",
                        "created_at": "2026-05-01T13:00:00Z",
                    },
                }
            }
        }


class ControlledEmbeddingProvider(EmbeddingProvider):
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [
            [
                float(text.lower().count("gate7")),
                float(text.lower().count("runtime")),
                float(text.lower().count("context")),
                float(text.lower().count("source")),
            ]
            for text in texts
        ]


class FakeLinkedPageFetcher:
    @property
    def resolver(self) -> Any:
        return lambda hostname: ("93.184.216.34",)

    async def fetch(self, url: object, source_id: str | None = None) -> FetchResult:
        del url, source_id
        raise AssertionError("Gate 7 runtime test post has no linked pages to fetch")


class FakeSearchProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    async def search_with_warnings(self, query: str, limit: int = 5) -> SearchBundle:
        self.calls.append((query, limit))
        documents = [
            ContextDocument(
                id=f"WEB-{index}",
                source_type="web",
                title=f"Gate 7 runtime source {index}",
                url=f"https://example.com/gate7-runtime-source-{index}",
                text=(
                    "Gate7 runtime context source support explains why the "
                    f"post is being discussed. Source detail {index}."
                ),
                metadata={"search_query": query, "rank": index},
            )
            for index in range(1, min(limit, 3) + 1)
        ]
        return SearchBundle(
            documents=documents,
            warnings=[f"gate7_search_warning:{query}:{limit}"],
        )


def test_gate7_default_api_path_uses_one_shot_search_rag(monkeypatch: Any) -> None:
    search_provider = FakeSearchProvider()
    captured_settings: dict[str, Any] = {}
    monkeypatch.setattr(
        retrieval_service,
        "OpenAIEmbeddingProvider",
        lambda *, settings: ControlledEmbeddingProvider(),
    )
    monkeypatch.setattr(
        retrieval_service,
        "_vector_store_or_fallback",
        lambda settings, vector_store: (InMemoryVectorStore(), []),
    )
    monkeypatch.setattr(retrieval_service, "LinkedPageFetcher", FakeLinkedPageFetcher)

    def default_search_providers(settings: Any, fetcher: Any) -> list[FakeSearchProvider]:
        del fetcher
        captured_settings["retrieval"] = settings
        return [search_provider]

    monkeypatch.setattr(retrieval_service, "_default_search_providers", default_search_providers)
    service = build_gate3_explainer(
        bluesky_client=BlueskyClient(client=Gate7AtprotoClient()),
        settings=Settings(openai_api_key=None),
    )
    route_client = TestClient(create_app(explainer=service))

    response = route_client.post(
        "/api/explain",
        json={"post_url": GATE7_URL, "provider": "openai", "include_trace": True},
    )

    assert response.status_code == 200
    payload = response.json()
    validated = ExplainResponse.model_validate(payload)
    assert type(service).__name__ == "AgentExplainerService"
    assert type(service._retriever).__name__ == "RetrievalEvidenceRetriever"  # noqa: SLF001
    runtime_settings = captured_settings["retrieval"]
    assert runtime_settings.max_queries == 3
    assert runtime_settings.search_limit_per_provider == 3
    assert runtime_settings.linked_page_limit == 3
    assert runtime_settings.linked_page_concurrency == 4
    assert runtime_settings.search_concurrency == 4
    assert runtime_settings.retrieval_timeout_seconds == 25.0
    assert search_provider.calls
    assert all(limit == 3 for _, limit in search_provider.calls)
    assert 1 <= len(validated.trace.queries) <= 3
    assert not any(
        warning == "search_rag_not_connected_using_thread_context_evidence"
        for warning in validated.trace.warnings
    )
    assert any(warning.startswith("gate7_search_warning:") for warning in validated.trace.warnings)
    assert any(source.type == "web" for source in validated.sources)
    source_ids = {source.id for source in validated.sources}
    cited_ids = {source_id for bullet in validated.bullets for source_id in bullet.source_ids}
    assert cited_ids <= source_ids


class FourQueryRunner(HeuristicSignatureRunner):
    def generate_queries(self, post: PostContext, category: str) -> list[str]:
        del post, category
        return ["alpha context", "beta context", "beta context", "gamma context", "delta context"]


class CapturingFullResultRetriever:
    warnings = ("retriever_warning_accessor",)

    def __init__(self) -> None:
        self.queries: list[str] = []
        self.calls: list[list[str]] = []
        self.retrieve_called = False
        self.retrieve_result_called = False
        self.retrieve_result_calls = 0

    def retrieve(
        self,
        post: PostContext,
        queries: Sequence[str] = (),
    ) -> tuple[Sequence[Evidence], Sequence[ContextDocument]]:
        del post, queries
        self.retrieve_called = True
        raise AssertionError("Agent service should prefer full retrieval result diagnostics")

    def retrieve_result(self, post: PostContext, queries: Sequence[str] = ()) -> d.RetrievalResult:
        del post
        self.retrieve_result_called = True
        self.retrieve_result_calls += 1
        self.queries = list(queries)
        self.calls.append(list(queries))
        documents = [
            ContextDocument(
                id=f"D{index}",
                source_type="web",
                title=f"Diagnostic source {index}",
                url=f"https://example.com/diagnostic-{index}",
                text=f"Diagnostic evidence {index} supports the runtime explanation.",
                metadata={},
            )
            for index in range(1, 4)
        ]
        evidence = [
            Evidence(
                id=f"E{index}",
                document_id=f"D{index}",
                text=f"Diagnostic evidence {index} supports the runtime explanation.",
                score=0.91,
                source_id=f"D{index}",
            )
            for index in range(1, 4)
        ]
        return d.make_retrieval_result(
            documents=documents,
            evidence=evidence,
            queries=list(queries),
            prompt_flags=["prompt_injection_risk"],
            warnings=["search_warning", "sanitizer_warning"],
            private_url_blocks=[
                "blocked_link:http://127.0.0.1/private:blocked_non_public_ip:127.0.0.1"
            ],
            extra_guardrail_flags=["unsafe_source"],
        )


class StaticFetcher:
    def fetch_context(self, url: str) -> PostContext:
        return PostContext(
            url=url,
            at_uri="at://did:plc:gate7/app.bsky.feed.post/3runtime",
            author="example.com",
            text="Gate 7 diagnostic trace check.",
            created_at=datetime(2026, 5, 1, 13, 30, tzinfo=UTC),
        )


class WarningFetcher:
    def fetch_context(self, url: str) -> PostContext:
        return (
            StaticFetcher()
            .fetch_context(url)
            .model_copy(update={"warnings": ["post_context_warning"]})
        )


def test_gate7_service_preserves_full_retrieval_diagnostics_and_caps_queries() -> None:
    retriever = CapturingFullResultRetriever()
    service = AgentExplainerService(
        fetcher=StaticFetcher(),
        retriever=retriever,
        program=BlueskyExplainer(runner=FourQueryRunner()),
    )

    response = service.explain(ExplainRequest(post_url=GATE7_URL, provider="openai"))

    assert retriever.retrieve_result_called is True
    assert retriever.retrieve_result_calls == 2
    assert retriever.retrieve_called is False
    assert retriever.calls[0] == ["alpha context", "beta context", "gamma context"]
    assert len(retriever.calls[1]) == 1
    assert response.trace.queries == [*retriever.calls[0], *retriever.calls[1]]
    assert "search_warning" in response.trace.warnings
    assert "sanitizer_warning" in response.trace.warnings
    assert any("blocked_link:http://127.0.0.1" in item for item in response.trace.warnings)
    assert "prompt_injection_risk" in response.trace.guardrail_flags
    assert "private_url_blocked" in response.trace.guardrail_flags
    assert "unsafe_source" in response.trace.guardrail_flags


def test_gate7_post_context_warning_wrapper_preserves_full_retrieval_result() -> None:
    retriever = CapturingFullResultRetriever()
    service = AgentExplainerService(
        fetcher=WarningFetcher(),
        retriever=PostContextWarningRetriever(retriever),
        program=BlueskyExplainer(runner=FourQueryRunner()),
    )

    response = service.explain(ExplainRequest(post_url=GATE7_URL, provider="openai"))

    assert retriever.retrieve_result_called is True
    assert retriever.retrieve_result_calls == 2
    assert retriever.retrieve_called is False
    assert len(retriever.calls[1]) == 1
    assert "post_context_warning" in response.trace.warnings
    assert "search_warning" in response.trace.warnings
    assert "private_url_blocked" in response.trace.guardrail_flags
