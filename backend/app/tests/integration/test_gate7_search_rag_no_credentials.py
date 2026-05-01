from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi.testclient import TestClient

from app.clients.bsky import BlueskyClient
from app.config import Settings
from app.deps import build_gate3_explainer
from app.main import create_app
from app.ml import retrieval_service
from app.ml.vector_store import InMemoryVectorStore
from app.schemas.api import ExplainResponse

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
                        "text": "Gate7 no credential runtime should fall back safely.",
                        "created_at": "2026-05-01T13:00:00Z",
                    },
                }
            }
        }


def test_gate7_default_search_rag_no_credentials_falls_back_with_trace(
    monkeypatch: Any,
) -> None:
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
    validated = ExplainResponse.model_validate(response.json())
    assert type(service._retriever).__name__ == "RetrievalEvidenceRetriever"  # noqa: SLF001
    assert "rag_runtime_failed:RuntimeError" in validated.trace.warnings
    assert "retrieval_unavailable" in validated.trace.guardrail_flags
    assert validated.trace.fallback_mode in {"abstain", "safe_summary", "partial"}
