"""Provider comparison report with live runs for configured providers."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import Settings
from app.deps import get_provider_catalog
from app.eval.dataset import DEFAULT_CASES_PATH, REPO_ROOT, load_eval_cases

DEFAULT_OUTPUT_MARKDOWN = REPO_ROOT / "reports" / "provider_comparison.md"
DEFAULT_OUTPUT_JSON = REPO_ROOT / "reports" / "provider_comparison.json"


@dataclass(frozen=True)
class ProviderRun:
    provider: str
    status: str
    configured: bool
    skipped_reason: str | None
    url: str | None = None
    status_code: int | None = None
    bullet_count: int = 0
    cited_bullet_count: int = 0
    source_count: int = 0
    fallback_mode: str | None = None
    adapter_mode: str | None = None
    quality_pass: bool = False
    warning_count: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "status": self.status,
            "configured": self.configured,
            "skipped_reason": self.skipped_reason,
            "url": self.url,
            "status_code": self.status_code,
            "bullet_count": self.bullet_count,
            "cited_bullet_count": self.cited_bullet_count,
            "source_count": self.source_count,
            "fallback_mode": self.fallback_mode,
            "adapter_mode": self.adapter_mode,
            "quality_pass": self.quality_pass,
            "warning_count": self.warning_count,
        }


def build_provider_comparison(
    *,
    settings: Settings | None = None,
    cases_path: Path = DEFAULT_CASES_PATH,
    live: bool = False,
    max_cases: int = 1,
    client: Any | None = None,
) -> dict[str, object]:
    active_settings = settings or Settings()
    providers = get_provider_catalog(active_settings)
    urls = _public_case_urls(cases_path, limit=max_cases)
    runs: list[ProviderRun] = []
    for provider in providers:
        if not provider.configured:
            runs.append(
                ProviderRun(
                    provider=provider.name,
                    status="skipped",
                    configured=False,
                    skipped_reason=provider.skipped_reason,
                )
            )
            continue
        if not live:
            runs.append(
                ProviderRun(
                    provider=provider.name,
                    status="configured_not_run",
                    configured=True,
                    skipped_reason=(
                        "live comparison disabled; pass --live to run configured providers"
                    ),
                )
            )
            continue
        runs.extend(_run_provider_cases(provider.name, urls, active_settings, client=client))
    return {
        "mode": "live" if live else "catalog",
        "case_count": len(urls),
        "providers": [run.as_dict() for run in runs],
    }


def write_provider_comparison(
    result: dict[str, object],
    *,
    markdown_path: Path = DEFAULT_OUTPUT_MARKDOWN,
    json_path: Path = DEFAULT_OUTPUT_JSON,
) -> dict[str, str]:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(_markdown(result), encoding="utf-8")
    return {"markdown": str(markdown_path), "json": str(json_path)}


def _run_provider_cases(
    provider_name: str,
    urls: list[str],
    settings: Settings,
    *,
    client: Any | None,
) -> list[ProviderRun]:
    active_client = client or _test_client()
    openai_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
    runs: list[ProviderRun] = []
    for url in urls:
        payload: dict[str, object] = {
            "post_url": url,
            "provider": provider_name,
            "include_trace": True,
        }
        if openai_key:
            payload["api_key"] = openai_key
        response = active_client.post("/api/explain", json=payload)
        runs.append(_provider_run_from_response(provider_name, url, response))
    return runs


def _provider_run_from_response(provider_name: str, url: str, response: Any) -> ProviderRun:
    payload = _response_payload(response)
    bullets = _list_field(payload, "bullets")
    sources = _list_field(payload, "sources")
    trace = _mapping_field(payload, "trace")
    fallback = _optional_text(trace.get("fallback_mode"))
    adapter = _optional_text(trace.get("adapter_mode"))
    cited_count = _cited_bullet_count(bullets)
    status_code = int(response.status_code)
    return ProviderRun(
        provider=provider_name,
        status=_provider_status(status_code),
        configured=True,
        skipped_reason=_provider_skip_reason(status_code),
        url=url,
        status_code=status_code,
        bullet_count=len(bullets),
        cited_bullet_count=cited_count,
        source_count=len(sources),
        fallback_mode=fallback,
        adapter_mode=adapter,
        quality_pass=_quality_pass(
            status_code=status_code,
            bullet_count=len(bullets),
            cited_bullet_count=cited_count,
            source_count=len(sources),
            fallback_mode=fallback,
        ),
        warning_count=_warning_count(trace),
    )


def _response_payload(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001 - report non-JSON provider failures.
        return {}
    return payload if isinstance(payload, dict) else {}


def _list_field(payload: Mapping[str, Any], key: str) -> list[Any]:
    value = payload.get(key, [])
    return value if isinstance(value, list) else []


def _mapping_field(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key, {})
    return value if isinstance(value, dict) else {}


def _optional_text(value: Any) -> str | None:
    return str(value) if value is not None else None


def _cited_bullet_count(bullets: list[Any]) -> int:
    return sum(1 for bullet in bullets if _has_citation(bullet))


def _has_citation(bullet: Any) -> bool:
    return isinstance(bullet, dict) and bool(bullet.get("source_ids"))


def _warning_count(trace: Mapping[str, Any]) -> int:
    warnings = trace.get("warnings", [])
    return len(warnings) if isinstance(warnings, list) else 0


def _quality_pass(
    *,
    status_code: int,
    bullet_count: int,
    cited_bullet_count: int,
    source_count: int,
    fallback_mode: str | None,
) -> bool:
    return all(
        (
            status_code == 200,
            3 <= bullet_count <= 5,
            cited_bullet_count == bullet_count,
            source_count > 0,
            fallback_mode != "abstain",
        )
    )


def _provider_status(status_code: int) -> str:
    return "ran" if status_code == 200 else "failed"


def _provider_skip_reason(status_code: int) -> str | None:
    return None if status_code == 200 else f"http_{status_code}"


def _public_case_urls(cases_path: Path, *, limit: int) -> list[str]:
    cases = [case for case in load_eval_cases(cases_path) if case.is_public_fixture]
    return [case.url for case in cases[: max(1, limit)]]


def _test_client() -> Any:
    from fastapi.testclient import TestClient

    from app.main import create_app

    return TestClient(create_app())


def _markdown(result: dict[str, object]) -> str:
    rows = result.get("providers", [])
    lines = [
        "# Provider Comparison",
        "",
        f"- Mode: `{result.get('mode')}`",
        f"- Case count: `{result.get('case_count')}`",
        "",
        "| Provider | Status | Configured | Quality Pass | Bullets | Sources | Fallback | Notes |",
        "|---|---|---:|---:|---:|---:|---|---|",
    ]
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            lines.append(
                "| {provider} | {status} | {configured} | {quality} | {bullets} | "
                "{sources} | {fallback} | {notes} |".format(
                    provider=row.get("provider"),
                    status=row.get("status"),
                    configured=row.get("configured"),
                    quality=row.get("quality_pass"),
                    bullets=row.get("bullet_count"),
                    sources=row.get("source_count"),
                    fallback=row.get("fallback_mode") or "",
                    notes=row.get("skipped_reason") or f"warnings={row.get('warning_count')}",
                )
            )
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write provider comparison report.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUTPUT_MARKDOWN)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--max-cases", type=int, default=1)
    parser.add_argument("--require-openai", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = Settings()
    if args.require_openai and settings.openai_api_key is None:
        raise SystemExit("OPENAI_API_KEY is required for live provider comparison.")
    result = build_provider_comparison(
        settings=settings,
        cases_path=args.cases,
        live=args.live,
        max_cases=args.max_cases,
    )
    paths = write_provider_comparison(result, markdown_path=args.out_md, json_path=args.out_json)
    print(json.dumps({"summary": result, "paths": paths}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
