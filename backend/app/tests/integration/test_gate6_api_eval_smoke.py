from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi.testclient import TestClient

from app.clients.bsky import BlueskyClient, BlueskyClientError, InvalidBlueskyPostUrlError
from app.config import Settings
from app.deps import build_gate3_explainer
from app.main import create_app
from app.ml import retrieval_service
from app.ml.embeddings import DeterministicHashEmbeddingProvider
from app.ml.vector_store import InMemoryVectorStore
from app.schemas.api import ExplainRequest, ExplainResponse

GATE6_SMOKE_URL = "https://bsky.app/profile/example.com/post/3gate6smoke"
TRACE_FIELDS = {
    "category",
    "queries",
    "warnings",
    "latency_ms",
    "trust_score",
    "fallback_mode",
    "guardrail_flags",
    "adapter_mode",
}


@dataclass
class ResolveResponse:
    did: str


class Gate6ReadOnlyAtprotoClient:
    """Controlled public-read client; it intentionally exposes no write methods."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def resolve_handle(self, handle: str) -> ResolveResponse:
        self.calls.append("resolve_handle")
        assert handle == "example.com"
        return ResolveResponse(did="did:plc:gate6target")

    def get_post_thread(self, uri: str, depth: int, parent_height: int) -> dict[str, object]:
        self.calls.append("get_post_thread")
        assert uri == "at://did:plc:gate6target/app.bsky.feed.post/3gate6smoke"
        assert depth == 3
        assert parent_height == 2
        return {
            "thread": {
                "post": {
                    "uri": uri,
                    "cid": "gate6-cid",
                    "indexed_at": "2026-05-01T12:00:10Z",
                    "author": {
                        "did": "did:plc:gate6target",
                        "handle": "example.com",
                    },
                    "record": {
                        "text": "Why is this project update suddenly being discussed?",
                        "created_at": "2026-05-01T12:00:00Z",
                    },
                    "embed": {
                        "record": {
                            "record": {
                                "uri": "at://did:plc:quote/app.bsky.feed.post/3quote",
                                "cid": "quote-cid",
                                "author": {
                                    "did": "did:plc:quote",
                                    "handle": "quote.example",
                                },
                                "value": {
                                    "text": "The quoted update names the project milestone.",
                                    "created_at": "2026-05-01T11:55:00Z",
                                },
                            }
                        },
                    },
                },
                "parent": {
                    "post": {
                        "uri": "at://did:plc:parent/app.bsky.feed.post/3parent",
                        "author": {
                            "did": "did:plc:parent",
                            "handle": "parent.example",
                        },
                        "record": {
                            "text": "Parent reply adds that people are asking for context.",
                            "created_at": "2026-05-01T11:59:00Z",
                        },
                    },
                    "parent": {"$type": "app.bsky.feed.defs#blockedPost", "blocked": True},
                },
            }
        }


def test_gate6_api_eval_smoke_uses_real_gate5_path_with_trace(monkeypatch: Any) -> None:
    atproto_client = Gate6ReadOnlyAtprotoClient()
    _install_controlled_retrieval(monkeypatch)
    service = build_gate3_explainer(
        bluesky_client=BlueskyClient(client=atproto_client),
        settings=Settings(),
    )
    route_client = TestClient(create_app(explainer=service))

    response = route_client.post(
        "/api/explain",
        json={
            "post_url": GATE6_SMOKE_URL,
            "provider": "openai",
            "include_trace": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    validated = ExplainResponse.model_validate(payload)
    assert type(service).__name__ == "AgentExplainerService"
    assert type(service._retriever).__name__ == "RetrievalEvidenceRetriever"  # noqa: SLF001
    assert atproto_client.calls == ["resolve_handle", "get_post_thread"]
    assert set(payload["trace"]) >= TRACE_FIELDS
    assert validated.trace.category
    assert validated.trace.queries
    assert isinstance(validated.trace.warnings, list)
    assert isinstance(validated.trace.guardrail_flags, list)
    assert validated.trace.adapter_mode in {"none", "deterministic_dev"}
    assert "Parent Bluesky post is blocked." in validated.trace.warnings
    assert "search_rag_not_connected_using_thread_context_evidence" not in (
        validated.trace.warnings
    )

    returned_source_ids = {source.id for source in validated.sources}
    cited_source_ids = {
        source_id for bullet in validated.bullets for source_id in bullet.source_ids
    }
    assert cited_source_ids
    assert cited_source_ids <= returned_source_ids
    if validated.trace.fallback_mode != "abstain":
        assert 3 <= len(validated.bullets) <= 5
        assert all(bullet.source_ids for bullet in validated.bullets)


def test_gate6_invalid_url_response_is_clean() -> None:
    route_client = TestClient(create_app(explainer=ShouldNotBeCalledExplainer()))

    response = route_client.post(
        "/api/explain",
        json={"post_url": "https://example.com/not-a-bluesky-post", "provider": "openai"},
    )

    assert response.status_code == 422
    serialized = response.text.lower()
    assert "traceback" not in serialized
    assert "openai_api_key" not in serialized
    assert "sk-test-secret" not in serialized


def test_gate6_typed_route_errors_do_not_leak_provider_details() -> None:
    route_client = TestClient(create_app(explainer=LeakyFailureExplainer()))

    response = route_client.post(
        "/api/explain",
        json={"post_url": GATE6_SMOKE_URL, "provider": "openai"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == {
        "code": "bluesky_fetch_failed",
        "message": "Unable to fetch Bluesky post context.",
    }
    serialized = response.text.lower()
    assert "traceback" not in serialized
    assert "openai_api_key" not in serialized
    assert "sk-test-secret" not in serialized


def test_gate6_late_invalid_url_error_is_typed_and_sanitized() -> None:
    route_client = TestClient(create_app(explainer=InvalidUrlExplainer()))

    response = route_client.post(
        "/api/explain",
        json={"post_url": GATE6_SMOKE_URL, "provider": "openai"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "invalid_bluesky_url",
        "message": "Expected https://bsky.app/profile/{actor}/post/{rkey}",
    }
    serialized = response.text.lower()
    assert "traceback" not in serialized
    assert "openai_api_key" not in serialized
    assert "sk-test-secret" not in serialized


def test_gate6_public_api_routes_remain_available() -> None:
    route_client = TestClient(create_app(explainer=ShouldNotBeCalledExplainer()))

    assert route_client.get("/api/health").status_code == 200
    providers = route_client.get("/api/providers")
    assert providers.status_code == 200
    assert {"openai", "anthropic", "gemini", "ollama"} <= {
        provider["name"] for provider in providers.json()["providers"]
    }
    assert route_client.get("/docs").status_code == 200


class ShouldNotBeCalledExplainer:
    def explain(self, request: ExplainRequest) -> ExplainResponse:
        del request
        raise AssertionError("explainer should not be called")


class LeakyFailureExplainer:
    def explain(self, request: ExplainRequest) -> ExplainResponse:
        del request
        raise BlueskyClientError(
            "Traceback (most recent call last): OPENAI_API_KEY=sk-test-secret"
        )


class InvalidUrlExplainer:
    def explain(self, request: ExplainRequest) -> ExplainResponse:
        del request
        raise InvalidBlueskyPostUrlError(
            "Traceback (most recent call last): OPENAI_API_KEY=sk-test-secret"
        )


def _install_controlled_retrieval(monkeypatch: Any) -> None:
    original_builder = retrieval_service.build_retrieval_service

    def build_controlled_retrieval_service(
        *,
        settings: Settings | None = None,
    ) -> retrieval_service.RetrievalService:
        return original_builder(
            settings=settings,
            retrieval_settings=retrieval_service.RetrievalSettings(
                include_linked_pages=False,
                include_search=False,
                include_bluesky_search=False,
                include_web_search=False,
            ),
            embedding_provider=DeterministicHashEmbeddingProvider(),
            vector_store=InMemoryVectorStore(),
            search_providers=[],
        )

    monkeypatch.setattr(
        retrieval_service,
        "build_retrieval_service",
        build_controlled_retrieval_service,
    )
