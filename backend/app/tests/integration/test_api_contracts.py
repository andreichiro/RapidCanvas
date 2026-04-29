from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from pydantic import ValidationError
from pytest import raises

from app.main import create_app
from app.schemas.api import ExplainRequest, ExplainResponse

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


def test_explain_route_is_contract_frozen_without_fake_agent_output() -> None:
    response = client.post(
        "/api/explain",
        json={
            "post_url": "https://bsky.app/profile/example.com/post/3abcxyz",
            "provider": "openai",
            "include_trace": True,
        },
    )

    assert response.status_code == 501
    assert response.json()["detail"]["code"] == "explain_pipeline_not_implemented"


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
