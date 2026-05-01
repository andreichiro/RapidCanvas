from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event

from fastapi.testclient import TestClient
from pydantic import ValidationError
from pytest import raises

from app.agent.service import ThreadContextEvidenceRetriever
from app.clients.bsky import BlueskyClientError, InvalidBlueskyPostUrlError
from app.deps import PostContextWarningRetriever, build_gate3_explainer
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
            warnings=["Parent Bluesky post is unavailable or deleted."],
        )


def test_post_context_warnings_are_request_local_under_concurrency() -> None:
    first_entered = Event()
    release_first = Event()

    class BlockingRetriever:
        warnings = ("retriever_warning",)

        def retrieve(self, post: PostContext) -> tuple[list[object], list[object]]:
            if post.author == "first":
                first_entered.set()
                assert release_first.wait(timeout=5)
            return [], []

    wrapper = PostContextWarningRetriever(BlockingRetriever())

    def make_post(author: str, warning: str) -> PostContext:
        return PostContext(
            url=f"https://bsky.app/profile/{author}/post/3abcxyz",
            at_uri=f"at://did:plc:{author}/app.bsky.feed.post/3abcxyz",
            author=author,
            text="Post text",
            created_at=datetime(2026, 4, 29, tzinfo=UTC),
            warnings=[warning],
        )

    def first_request() -> tuple[str, ...]:
        wrapper.retrieve(make_post("first", "first_warning"))
        return tuple(wrapper.warnings)

    def second_request() -> tuple[str, ...]:
        assert first_entered.wait(timeout=5)
        wrapper.retrieve(make_post("second", "second_warning"))
        warnings = tuple(wrapper.warnings)
        release_first.set()
        return warnings

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(first_request)
        second = pool.submit(second_request)

    assert second.result(timeout=5) == ("retriever_warning", "second_warning")
    assert first.result(timeout=5) == ("retriever_warning", "first_warning")


class InvalidUrlExplainer:
    def explain(self, request: ExplainRequest) -> ExplainResponse:
        raise InvalidBlueskyPostUrlError("unsupported post URL")


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


def test_explainer_uses_dev_c_agent_program_with_thread_context_fallback() -> None:
    route_client = TestClient(
        create_app(
            explainer=build_gate3_explainer(
                bluesky_client=FakeBlueskyClient(),
                retriever=ThreadContextEvidenceRetriever(),
            )
        )
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
    assert "Parent Bluesky post is unavailable or deleted." in payload["trace"]["warnings"]


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


def test_explain_route_maps_late_invalid_url_failure() -> None:
    route_client = TestClient(create_app(explainer=InvalidUrlExplainer()))
    response = route_client.post(
        "/api/explain",
        json={
            "post_url": "https://bsky.app/profile/example.com/post/3abcxyz",
            "provider": "openai",
            "include_trace": True,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_bluesky_url"


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
