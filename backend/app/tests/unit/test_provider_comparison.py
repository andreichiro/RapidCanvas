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
                {"id": "S1", "title": "Source 1", "url": "https://example.com", "type": "web"},
                {"id": "S2", "title": "Source 2", "url": "https://example.org", "type": "web"},
            ],
            "trace": {
                "fallback_mode": "none",
                "adapter_mode": "none",
                "warnings": ["provider_openai_default_used"],
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
    assert providers["anthropic"]["status"] == "skipped"
    assert client.requests[0]["provider"] == "openai"
    assert client.requests[0]["api_key"] == "sk-test-provider-key"
    assert "sk-test-provider-key" not in str(result)


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
    assert "per-request key path" in markdown
    assert "ANTHROPIC_API_KEY is not configured" in markdown
    assert '"provider": "openai"' in payload


def _provider_rows(result: dict[str, object]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], result["providers"])
