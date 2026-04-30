from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from pydantic import ValidationError
from pytest import raises

from app.clients.bsky import BlueskyClientError
from app.deps import build_gate3_explainer
from app.main import create_app
from app.schemas.api import (
    Bullet,
    ExplainRequest,
    ExplainResponse,
    PostSummary,
    Source,
    Trace,
)
from app.schemas.domain import PostContext

client = TestClient(create_app())


def test_health_route_returns_contract() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_providers_route_lists_configured_and_skipped_providers() -> None:
    response = client.get("/api/providers")

    assert response.status_code == 200
    providers = response.json()["providers"]
    provider_names = {provider["name"] for provider in providers}
    assert {"openai", "anthropic", "gemini", "ollama"} <= provider_names
    assert all("configured" in provider for provider in providers)


def test_explain_request_rejects_non_bluesky_post_url() -> None:
    response = client.post(
        "/api/explain",
        json={"post_url": "https://example.com/not-a-bluesky-post", "provider": "openai"},
    )

    assert response.status_code == 422


class FakeExplainer:
    def explain(self, request: ExplainRequest) -> ExplainResponse:
        return ExplainResponse(
            post=PostSummary(
                url=request.post_url,
                author="example.com",
                text="A real fetched post would be summarized here.",
                created_at=datetime(2026, 4, 29, tzinfo=UTC),
            ),
            bullets=[
                Bullet(text="Fetched post text is available.", source_ids=["S1"]),
                Bullet(text="Trace marks deterministic adapters.", source_ids=["S1"]),
                Bullet(text="This is not final Search/RAG or DSPy behavior.", source_ids=["S1"]),
            ],
            sources=[
                Source(
                    id="S1",
                    title="Bluesky post by example.com",
                    url=request.post_url,
                    type="thread",
                    snippet="A real fetched post would be summarized here.",
                )
            ],
            trace=Trace(
                category="gate3_vertical_slice",
                warnings=["real_bluesky_fetch_enabled"],
                trust_score=0.35,
                fallback_mode="safe_summary",
                guardrail_flags=["dev_adapter_search_rag", "dev_adapter_dspy"],
                adapter_mode="deterministic_dev",
                adapter_notes=["Real Bluesky fetch active; adapters are non-final."],
            ),
        )


class FailingExplainer:
    def explain(self, request: ExplainRequest) -> ExplainResponse:
        raise BlueskyClientError("upstream unavailable")


class FakeBlueskyClient:
    def fetch_context(self, url: str) -> PostContext:
        return PostContext(
            url=url,
            at_uri="at://did:plc:example/app.bsky.feed.post/3abcxyz",
            author="example.com",
            text="A fetched post routed through the Dev C agent.",
            created_at=datetime(2026, 4, 29, tzinfo=UTC),
            parent_texts=[
                "Parent context explains the reference.",
                "Another parent adds source-backed context.",
            ],
        )


def test_explain_route_returns_schema_valid_gate3_response() -> None:
    route_client = TestClient(create_app(explainer=FakeExplainer()))
    response = route_client.post(
        "/api/explain",
        json={
            "post_url": "https://bsky.app/profile/example.com/post/3abcxyz",
            "provider": "openai",
            "include_trace": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["bullets"]) == 3
    assert payload["trace"]["fallback_mode"] == "safe_summary"
    assert payload["trace"]["adapter_mode"] == "deterministic_dev"
    assert "dev_adapter_dspy" in payload["trace"]["guardrail_flags"]


def test_default_explainer_uses_dev_c_agent_program() -> None:
    route_client = TestClient(
        create_app(explainer=build_gate3_explainer(bluesky_client=FakeBlueskyClient()))
    )

    response = route_client.post(
        "/api/explain",
        json={
            "post_url": "https://bsky.app/profile/example.com/post/3abcxyz",
            "provider": "openai",
            "include_trace": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["bullets"]) == 3
    assert payload["trace"]["category"] != "gate3_vertical_slice"
    assert payload["trace"]["adapter_mode"] == "deterministic_dev"
    assert "dev_c_api_path_uses_agent_guardrails" in payload["trace"]["warnings"]


def test_explain_route_maps_bluesky_fetch_failure() -> None:
    route_client = TestClient(create_app(explainer=FailingExplainer()))
    response = route_client.post(
        "/api/explain",
        json={
            "post_url": "https://bsky.app/profile/example.com/post/3abcxyz",
            "provider": "openai",
            "include_trace": True,
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "bluesky_fetch_failed"


def test_openapi_exposes_frozen_explain_contract() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    document = response.json()
    assert "/api/explain" in document["paths"]
    assert "ExplainRequest" in document["components"]["schemas"]
    assert "ExplainResponse" in document["components"]["schemas"]


def test_public_response_contract_requires_cited_three_to_five_bullets() -> None:
    payload = {
        "post": {
            "url": "https://bsky.app/profile/example.com/post/3abcxyz",
            "author": "example.com",
            "text": "Example post",
            "created_at": datetime(2026, 4, 29, tzinfo=UTC),
        },
        "bullets": [
            {"text": "Supported point one.", "source_ids": ["S1"]},
            {"text": "Supported point two.", "source_ids": ["S1"]},
            {"text": "Supported point three.", "source_ids": ["S1"]},
        ],
        "sources": [
            {
                "id": "S1",
                "title": "Example source",
                "url": "https://bsky.app/profile/example.com/post/3abcxyz",
                "type": "thread",
                "snippet": "Example post",
            }
        ],
        "trace": {
            "category": "example",
            "queries": ["example context"],
            "warnings": [],
            "latency_ms": 12,
            "trust_score": 0.8,
            "fallback_mode": "none",
            "guardrail_flags": [],
        },
    }

    validated = ExplainResponse.model_validate(payload)
    assert len(validated.bullets) == 3


def test_public_response_contract_rejects_uncited_bullet() -> None:
    with raises(ValidationError):
        ExplainResponse.model_validate(
            {
                "post": {
                    "url": "https://bsky.app/profile/example.com/post/3abcxyz",
                    "author": "example.com",
                    "text": "Example post",
                    "created_at": datetime(2026, 4, 29, tzinfo=UTC),
                },
                "bullets": [
                    {"text": "Unsupported point.", "source_ids": []},
                    {"text": "Supported point two.", "source_ids": ["S1"]},
                    {"text": "Supported point three.", "source_ids": ["S1"]},
                ],
                "sources": [
                    {
                        "id": "S1",
                        "title": "Example source",
                        "url": "https://bsky.app/profile/example.com/post/3abcxyz",
                        "type": "thread",
                        "snippet": "Example post",
                    }
                ],
                "trace": {"fallback_mode": "none"},
            }
        )


def test_bluesky_url_validator_accepts_expected_shape() -> None:
    request = ExplainRequest.model_validate(
        {
            "post_url": "https://bsky.app/profile/example.com/post/3abcxyz",
            "provider": "openai",
        }
    )

    assert request.post_url == "https://bsky.app/profile/example.com/post/3abcxyz"
