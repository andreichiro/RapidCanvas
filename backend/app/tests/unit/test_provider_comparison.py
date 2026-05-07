from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from pydantic import SecretStr

from app.config import Settings
from app.eval.provider_comparison import build_provider_comparison, write_provider_comparison


class FakeResponse:
    status_code = 200

    def json(self) -> dict[str, object]:
        return {
            "bullets": [
                {"text": "Useful cited point one.", "source_ids": ["S1"]},
                {"text": "Useful cited point two.", "source_ids": ["S1"]},
                {"text": "Useful cited point three.", "source_ids": ["S2"]},
            ],
            "sources": [
                {
                    "id": "S1",
                    "title": "Useful cited source",
                    "url": "https://example.com",
                    "type": "web",
                    "snippet": "Useful cited point one and useful cited point two.",
                },
                {
                    "id": "S2",
                    "title": "Useful supporting source",
                    "url": "https://example.org",
                    "type": "web",
                    "snippet": "Useful cited point three.",
                },
            ],
            "trace": {
                "fallback_mode": "none",
                "adapter_mode": "none",
                "warnings": ["provider_openai_live"],
            },
        }


class FakeClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def post(self, _url: str, *, json: dict[str, Any]) -> FakeResponse:
        self.requests.append(json)
        return FakeResponse()


def test_provider_comparison_catalog_reports_skipped_optionals() -> None:
    result = build_provider_comparison(settings=Settings(openai_api_key=None), live=False)
    providers = {row["provider"]: row for row in _provider_rows(result)}

    assert "per-request key path" in str(result["credential_scope"])
    assert providers["openai"]["status"] == "skipped"
    assert providers["anthropic"]["skipped_reason"] == "ANTHROPIC_API_KEY is not configured"
    assert providers["gemini"]["skipped_reason"] == "GEMINI_API_KEY is not configured"


def test_provider_comparison_live_runs_configured_openai_without_leaking_key() -> None:
    client = FakeClient()
    result = build_provider_comparison(
        settings=Settings(openai_api_key=SecretStr("sk-test-provider-key")),
        live=True,
        max_cases=1,
        client=client,
    )
    providers = {row["provider"]: row for row in _provider_rows(result)}

    assert providers["openai"]["status"] == "ran"
    assert providers["openai"]["quality_pass"] is True
    assert providers["openai"]["source_relevance_score"] >= 0.2
    assert providers["openai"]["answer_usefulness_score"] >= 0.8
    assert providers["anthropic"]["status"] == "skipped"
    assert result["comparison_status"] == "comparison incomplete"
    assert client.requests[0]["provider"] == "openai"
    assert client.requests[0]["api_key"] == "sk-test-provider-key"
    assert "sk-test-provider-key" not in str(result)


def test_provider_comparison_complete_requires_two_actual_provider_runs() -> None:
    client = FakeClient()
    result = build_provider_comparison(
        settings=Settings(
            openai_api_key=SecretStr("sk-test-provider-key"),
            anthropic_api_key=SecretStr("sk-test-anthropic-key"),
        ),
        live=True,
        max_cases=1,
        client=client,
    )

    assert result["ran_provider_count"] == 2
    assert result["comparison_status"] == "comparison complete"
    assert [request["provider"] for request in client.requests] == ["openai", "anthropic"]


def test_provider_comparison_complete_rejects_two_provider_fallbacks() -> None:
    class FallbackResponse(FakeResponse):
        def json(self) -> dict[str, object]:
            payload = super().json()
            payload["trace"] = {
                "fallback_mode": "none",
                "adapter_mode": "deterministic_fallback",
                "warnings": ["dspy_provider_error"],
                "guardrail_flags": ["dspy_provider_error"],
            }
            return payload

    class FallbackClient(FakeClient):
        def post(self, _url: str, *, json: dict[str, Any]) -> FakeResponse:
            self.requests.append(json)
            return FallbackResponse()

    result = build_provider_comparison(
        settings=Settings(
            openai_api_key=SecretStr("sk-test-provider-key"),
            anthropic_api_key=SecretStr("sk-test-anthropic-key"),
        ),
        live=True,
        max_cases=1,
        client=FallbackClient(),
    )
    providers = {row["provider"]: row for row in _provider_rows(result)}

    assert providers["openai"]["status"] == "ran"
    assert providers["anthropic"]["status"] == "ran"
    assert providers["openai"]["provider_quality_score"] == 0.0
    assert providers["anthropic"]["provider_quality_score"] == 0.0
    assert result["ran_provider_count"] == 0
    assert result["comparison_status"] == "comparison incomplete"


def test_provider_comparison_missing_trace_does_not_count_as_provider_run() -> None:
    class MissingTraceResponse(FakeResponse):
        def json(self) -> dict[str, object]:
            payload = super().json()
            payload.pop("trace", None)
            return payload

    class MissingTraceClient(FakeClient):
        def post(self, _url: str, *, json: dict[str, Any]) -> FakeResponse:
            self.requests.append(json)
            return MissingTraceResponse()

    result = build_provider_comparison(
        settings=Settings(
            openai_api_key=SecretStr("sk-test-provider-key"),
            anthropic_api_key=SecretStr("sk-test-anthropic-key"),
        ),
        live=True,
        max_cases=1,
        client=MissingTraceClient(),
    )
    providers = {row["provider"]: row for row in _provider_rows(result)}

    assert providers["openai"]["status"] == "ran"
    assert providers["anthropic"]["status"] == "ran"
    assert providers["openai"]["provider_quality_score"] == 0.0
    assert providers["anthropic"]["provider_quality_score"] == 0.0
    assert result["ran_provider_count"] == 0
    assert result["comparison_status"] == "comparison incomplete"


def test_provider_comparison_does_not_count_two_cases_as_two_providers() -> None:
    client = FakeClient()
    result = build_provider_comparison(
        settings=Settings(openai_api_key=SecretStr("sk-test-provider-key")),
        live=True,
        max_cases=2,
        client=client,
    )

    assert result["ran_provider_count"] == 1
    assert result["comparison_status"] == "comparison incomplete"
    assert [request["provider"] for request in client.requests] == ["openai", "openai"]


def test_provider_comparison_quality_fails_off_topic_sources() -> None:
    class OffTopicResponse(FakeResponse):
        def json(self) -> dict[str, object]:
            payload = super().json()
            payload["sources"] = [
                {
                    "id": "S1",
                    "title": "Trading card catalog",
                    "url": "https://cards.example.test/catalog",
                    "type": "web",
                    "snippet": "Coupon pricing for graded rookie card marketplace listings.",
                }
            ]
            return payload

    class OffTopicClient(FakeClient):
        def post(self, _url: str, *, json: dict[str, Any]) -> FakeResponse:
            self.requests.append(json)
            return OffTopicResponse()

    result = build_provider_comparison(
        settings=Settings(openai_api_key=SecretStr("sk-test-provider-key")),
        live=True,
        max_cases=1,
        client=OffTopicClient(),
    )
    providers = {row["provider"]: row for row in _provider_rows(result)}

    assert providers["openai"]["quality_pass"] is False
    assert providers["openai"]["source_relevance_score"] < 0.2


def test_provider_comparison_completion_requires_quality_passing_runs() -> None:
    class WeakResponse(FakeResponse):
        def json(self) -> dict[str, object]:
            payload = super().json()
            payload["bullets"] = [
                {"text": "Useful cited point one.", "source_ids": ["S1"]},
                {"text": "Useful cited point two.", "source_ids": ["S1"]},
                {"text": "Useful cited point three.", "source_ids": ["S1"]},
            ]
            payload["sources"] = [
                {
                    "id": "S1",
                    "title": "Unrelated source",
                    "url": "https://unrelated.example.test/story",
                    "type": "web",
                    "snippet": "Completely different subject matter with no material overlap.",
                }
            ]
            return payload

    class WeakClient(FakeClient):
        def post(self, _url: str, *, json: dict[str, Any]) -> FakeResponse:
            self.requests.append(json)
            return WeakResponse()

    result = build_provider_comparison(
        settings=Settings(
            openai_api_key=SecretStr("sk-test-provider-key"),
            anthropic_api_key=SecretStr("sk-test-anthropic-key"),
        ),
        live=True,
        max_cases=1,
        client=WeakClient(),
    )
    providers = {row["provider"]: row for row in _provider_rows(result)}

    assert providers["openai"]["status"] == "ran"
    assert providers["openai"]["provider_quality_score"] == 1.0
    assert providers["openai"]["quality_pass"] is False
    assert providers["anthropic"]["quality_pass"] is False
    assert result["ran_provider_count"] == 0
    assert result["comparison_status"] == "comparison incomplete"


def test_provider_comparison_rejects_keyword_stuffed_catalog_sources() -> None:
    class CatalogResponse(FakeResponse):
        def json(self) -> dict[str, object]:
            payload = super().json()
            payload["sources"] = [
                {
                    "id": "S1",
                    "title": "Useful cited source trading card catalog",
                    "url": "https://cards.example.test/catalog",
                    "type": "web",
                    "snippet": (
                        "Useful cited point one useful cited point two useful cited point three "
                        "coupon pricing marketplace listings."
                    ),
                }
            ]
            return payload

    class CatalogClient(FakeClient):
        def post(self, _url: str, *, json: dict[str, Any]) -> FakeResponse:
            self.requests.append(json)
            return CatalogResponse()

    result = build_provider_comparison(
        settings=Settings(openai_api_key=SecretStr("sk-test-provider-key")),
        live=True,
        max_cases=1,
        client=CatalogClient(),
    )
    providers = {row["provider"]: row for row in _provider_rows(result)}

    assert providers["openai"]["provider_quality_score"] == 1.0
    assert providers["openai"]["source_relevance_score"] == 0.0
    assert providers["openai"]["quality_pass"] is False


def test_provider_comparison_quality_fails_non_live_provider_fallback() -> None:
    class FallbackResponse(FakeResponse):
        def json(self) -> dict[str, object]:
            payload = super().json()
            payload["trace"] = {
                "fallback_mode": "none",
                "adapter_mode": "deterministic_fallback",
                "warnings": ["dspy_provider_error"],
                "guardrail_flags": ["dspy_provider_error"],
            }
            return payload

    class FallbackClient(FakeClient):
        def post(self, _url: str, *, json: dict[str, Any]) -> FakeResponse:
            self.requests.append(json)
            return FallbackResponse()

    result = build_provider_comparison(
        settings=Settings(openai_api_key=SecretStr("sk-test-provider-key")),
        live=True,
        max_cases=1,
        client=FallbackClient(),
    )
    providers = {row["provider"]: row for row in _provider_rows(result)}

    assert providers["openai"]["status"] == "ran"
    assert providers["openai"]["provider_quality_score"] == 0.0
    assert providers["openai"]["quality_pass"] is False


def test_provider_comparison_writes_markdown_and_json(tmp_path: Path) -> None:
    result = build_provider_comparison(settings=Settings(openai_api_key=None), live=False)
    paths = write_provider_comparison(
        result,
        markdown_path=tmp_path / "provider_comparison.md",
        json_path=tmp_path / "provider_comparison.json",
    )

    markdown = Path(paths["markdown"]).read_text(encoding="utf-8")
    payload = Path(paths["json"]).read_text(encoding="utf-8")
    assert "Provider Comparison" in markdown
    assert "Credential scope" in markdown
    assert "Comparison status" in markdown
    assert "per-request key path" in markdown
    assert "ANTHROPIC_API_KEY is not configured" in markdown
    assert '"provider": "openai"' in payload


def _provider_rows(result: dict[str, object]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], result["providers"])
