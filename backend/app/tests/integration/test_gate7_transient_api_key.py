from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from app.api.routes import create_api_router
from app.config import Settings
from app.schemas.api import (
    Bullet,
    ExplainRequest,
    ExplainResponse,
    PostSummary,
    Source,
    Trace,
)


class FakeExplainer:
    def explain(self, request: ExplainRequest) -> ExplainResponse:
        return ExplainResponse(
            post=PostSummary(
                url=request.post_url,
                author="example.com",
                text="A fetched post routed through the transient key path.",
                created_at=datetime(2026, 4, 29, tzinfo=UTC),
            ),
            bullets=[
                Bullet(text="The request key reached service settings.", source_ids=["S1"]),
                Bullet(text="The public response stays cited.", source_ids=["S1"]),
                Bullet(text="The secret is not reflected back to the caller.", source_ids=["S1"]),
            ],
            sources=[
                Source(
                    id="S1",
                    title="Bluesky post by example.com",
                    url=request.post_url,
                    type="thread",
                    snippet="A fetched post routed through the transient key path.",
                )
            ],
            trace=Trace(category="gate7_transient_key", trust_score=0.9, fallback_mode="none"),
        )


def test_default_explain_route_requires_api_key_when_env_key_absent() -> None:
    app = FastAPI()
    app.include_router(create_api_router(Settings(openai_api_key=None)))
    route_client = TestClient(app)

    response = route_client.post(
        "/api/explain",
        json={
            "post_url": "https://bsky.app/profile/example.com/post/3abcxyz",
            "provider": "openai",
            "include_trace": True,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "missing_openai_api_key"


def test_default_explain_route_uses_transient_request_api_key(
    monkeypatch: MonkeyPatch,
) -> None:
    captured_keys: list[str] = []

    def fake_builder(*, settings: Settings) -> FakeExplainer:
        assert settings.openai_api_key is not None
        captured_keys.append(settings.openai_api_key.get_secret_value())
        return FakeExplainer()

    monkeypatch.setattr("app.api.routes.build_gate3_explainer", fake_builder)
    app = FastAPI()
    app.include_router(create_api_router(Settings(openai_api_key=None)))
    route_client = TestClient(app)

    response = route_client.post(
        "/api/explain",
        json={
            "post_url": "https://bsky.app/profile/example.com/post/3abcxyz",
            "provider": "openai",
            "include_trace": True,
            "api_key": " sk-request-secret ",
        },
    )

    assert response.status_code == 200
    assert captured_keys == ["sk-request-secret"]
    assert "sk-request-secret" not in response.text


def test_explain_request_api_key_is_secret_and_trimmed() -> None:
    request = ExplainRequest.model_validate(
        {
            "post_url": "https://bsky.app/profile/example.com/post/3abcxyz",
            "provider": "openai",
            "api_key": " sk-request-secret ",
        }
    )

    assert request.api_key is not None
    assert request.api_key.get_secret_value() == "sk-request-secret"
    assert "sk-request-secret" not in repr(request)
    assert "sk-request-secret" not in request.model_dump_json()
