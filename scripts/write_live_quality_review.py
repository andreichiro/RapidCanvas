"""Write a curated live-quality review from the real FastAPI explain route."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.eval.dataset import EvalCase  # noqa: E402
from app.eval.metrics import expected_point_recall  # noqa: E402
from app.eval.quality_metrics import quality_metrics_for_prediction  # noqa: E402
from app.main import create_app  # noqa: E402

DEFAULT_CASES = ROOT / "eval" / "posts.yaml"
DEFAULT_OUT = ROOT / "docs" / "reviews" / "live_quality_review.md"


def public_cases(path: Path, limit: int) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    public = [case for case in cases if case.get("provenance") == "fixture_backed_public"]
    return public[: max(1, limit)]


def run_case(client: TestClient, case: dict[str, Any], api_key: str) -> dict[str, Any]:
    started = time.perf_counter()
    response = client.post(
        "/api/explain",
        json={
            "post_url": case["url"],
            "provider": "openai",
            "include_trace": True,
            "api_key": api_key,
        },
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    payload = response.json() if _is_json_response(response) else {}
    return summarize_case(case, payload, response.status_code, elapsed_ms)


def summarize_case(
    case: dict[str, Any],
    payload: dict[str, Any],
    status_code: int,
    elapsed_ms: int,
) -> dict[str, Any]:
    trace = _mapping(payload.get("trace"))
    bullets = _list(payload.get("bullets"))
    sources = _list(payload.get("sources"))
    warnings = _list(trace.get("warnings"))
    cited = sum(1 for bullet in bullets if _list(_mapping(bullet).get("source_ids")))
    eval_case = EvalCase.model_validate(case)
    point_recall = expected_point_recall(eval_case, payload)
    quality = quality_metrics_for_prediction(
        eval_case,
        payload,
        point_recall=point_recall,
        citation_coverage=cited / max(len(bullets), 1),
    )
    vector_backend = str(trace.get("vector_store_backend") or qdrant_status(warnings))
    passed = meaningful(status_code, bullets, cited, sources, trace, quality)
    failure = failure_reason(status_code, bullets, cited, sources, trace, quality, point_recall)
    return {
        "id": case.get("id"),
        "url": case.get("url"),
        "status_code": status_code,
        "latency_ms": elapsed_ms,
        "fallback_mode": trace.get("fallback_mode"),
        "adapter_mode": trace.get("adapter_mode"),
        "vector_backend": vector_backend,
        "meaningful": passed,
        "failure_reason": failure,
        "expected_point_recall": point_recall,
        "source_relevance_score": quality["source_relevance_score"],
        "citation_relevance_score": quality["citation_relevance_score"],
        "off_topic_source_count": quality["off_topic_source_count"],
        "ineligible_citation_count": quality["ineligible_citation_count"],
        "answer_usefulness_score": quality["answer_usefulness_score"],
        "public_live_quality_pass": quality["public_live_quality_pass"],
        "provider_quality_score": quality["provider_quality_score"],
        "image_evidence_used": quality["image_evidence_used"],
        "image_expected_point_recall": quality["image_expected_point_recall"],
        "bullets": bullets,
        "sources": [_source_summary(source) for source in sources],
        "warnings": [str(warning) for warning in warnings],
        "warning_count": len(warnings),
    }


def qdrant_status(warnings: list[Any]) -> str:
    text = "\n".join(str(item) for item in warnings)
    if "qdrant_vector_store" in text:
        return "qdrant_vector_store"
    if "in_memory_fallback" in text or "qdrant_unavailable" in text:
        return "in_memory_fallback"
    return "not_reported"


def meaningful(
    status_code: int,
    bullets: list[Any],
    cited_count: int,
    sources: list[Any],
    trace: dict[str, Any],
    quality: dict[str, float | int],
) -> bool:
    quality_pass = float(quality.get("public_live_quality_pass", 0.0)) == 1.0
    return all(
        (
            status_code == 200,
            3 <= len(bullets) <= 5,
            cited_count == len(bullets),
            bool(sources),
            trace.get("adapter_mode") == "none",
            int(quality.get("off_topic_source_count", 0)) == 0,
            quality_pass,
        )
    )


def failure_reason(
    status_code: int,
    bullets: list[Any],
    cited_count: int,
    sources: list[Any],
    trace: dict[str, Any],
    quality: dict[str, float | int],
    point_recall: float,
) -> str:
    quality_pass = float(quality.get("public_live_quality_pass", 0.0)) == 1.0
    checks = [
        (status_code != 200, f"http_status_{status_code}"),
        (not 3 <= len(bullets) <= 5, "wrong_bullet_count"),
        (cited_count != len(bullets), "missing_bullet_citations"),
        (not sources, "no_sources_returned"),
        (trace.get("adapter_mode") != "none", "adapter_mode_not_none"),
        (point_recall < 0.66 and not quality_pass, "low_expected_point_recall"),
        (int(quality.get("ineligible_citation_count", 0)) > 0, "ineligible_citation"),
        (int(quality.get("off_topic_source_count", 0)) > 0, "off_topic_cited_source"),
        (
            float(quality.get("source_relevance_score", 0.0)) < 0.40 and not quality_pass,
            "low_source_relevance",
        ),
        (
            float(quality.get("citation_relevance_score", 0.0)) < 0.12 and not quality_pass,
            "low_citation_relevance",
        ),
        (
            float(quality.get("answer_usefulness_score", 0.0)) < 0.75 and not quality_pass,
            "low_answer_usefulness",
        ),
        (
            float(quality.get("provider_quality_score", 0.0)) < 1.0 and not quality_pass,
            "provider_quality_failed",
        ),
        (
            trace.get("fallback_mode") == "abstain" and not quality_pass,
            "abstained",
        ),
        (not quality_pass, "quality_threshold_failed"),
    ]
    for failed, reason in checks:
        if failed:
            return reason
    return "passed"


def live_quality_failures(
    rows: list[dict[str, Any]],
    *,
    min_passes: int = 8,
) -> dict[str, Any]:
    pass_count = sum(1 for row in rows if row.get("meaningful") is True)
    missing_reasons = sum(1 for row in rows if _missing_failure_reason(row))
    off_topic_passes = _passing_count(rows, "off_topic_source_count")
    ineligible_passes = _passing_count(rows, "ineligible_citation_count")
    adapter_passes = sum(1 for row in rows if _adapter_pass(row))
    blocking = _blocking_failures(
        rows=rows,
        pass_count=pass_count,
        min_passes=min_passes,
        missing_reasons=missing_reasons,
        off_topic_passes=off_topic_passes,
        ineligible_passes=ineligible_passes,
        adapter_passes=adapter_passes,
    )
    return {
        "pass_count": pass_count,
        "missing_failure_reasons": missing_reasons,
        "off_topic_passes": off_topic_passes,
        "ineligible_passes": ineligible_passes,
        "adapter_passes": adapter_passes,
        "blocking_failures": blocking,
    }


def _missing_failure_reason(row: dict[str, Any]) -> bool:
    reason = str(row.get("failure_reason") or "").strip()
    return row.get("meaningful") is not True and reason in {"", "passed"}


def _passing_count(rows: list[dict[str, Any]], count_key: str) -> int:
    return sum(
        1 for row in rows if row.get("meaningful") is True and int(row.get(count_key, 0)) > 0
    )


def _adapter_pass(row: dict[str, Any]) -> bool:
    return row.get("meaningful") is True and row.get("adapter_mode") != "none"


def _blocking_failures(
    *,
    rows: list[dict[str, Any]],
    pass_count: int,
    min_passes: int,
    missing_reasons: int,
    off_topic_passes: int,
    ineligible_passes: int,
    adapter_passes: int,
) -> list[str]:
    blocking: list[str] = []
    if len(rows) != 10:
        blocking.append(f"expected_10_public_rows_got_{len(rows)}")
    if pass_count < min_passes:
        blocking.append(f"useful_pass_count_{pass_count}_below_{min_passes}")
    if missing_reasons:
        blocking.append(f"failed_rows_without_reason_{missing_reasons}")
    if off_topic_passes:
        blocking.append(f"off_topic_passing_rows_{off_topic_passes}")
    if ineligible_passes:
        blocking.append(f"ineligible_citation_passing_rows_{ineligible_passes}")
    if adapter_passes:
        blocking.append(f"adapter_passing_rows_{adapter_passes}")
    return blocking


def render_markdown(rows: list[dict[str, Any]]) -> str:
    pass_count = sum(1 for row in rows if row["meaningful"])
    failure_summary = live_quality_failures(rows)
    lines = [
        "# Live Quality Review",
        "",
        "Generated by `make live-quality-review` against the real FastAPI",
        "explainer route. An OpenAI key was supplied locally through",
        "`OPENAI_API_KEY` and sent only as a transient request key; no key is",
        "written to this file or project settings.",
        "",
        f"- Cases run: `{len(rows)}`",
        f"- Meaningful pass count: `{pass_count}`",
        f"- Failed rows without reason: `{failure_summary['missing_failure_reasons']}`",
        f"- Off-topic passing rows: `{failure_summary['off_topic_passes']}`",
        f"- Ineligible-citation passing rows: `{failure_summary['ineligible_passes']}`",
        f"- Passing rows with non-live adapter: `{failure_summary['adapter_passes']}`",
        f"- Live quality gate: `{'pass' if not failure_summary['blocking_failures'] else 'fail'}`",
        "",
        "| Case | Status | Fallback | Useful | Recall | Source Rel. | Citation Rel. | "
        "Provider Q. | Off Topic | Ineligible | Adapter | Vector | Latency | Failure |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---|",
    ]
    for row in rows:
        lines.append(_summary_row(row))
    lines.extend(["", "## Returned Bullets", ""])
    for row in rows:
        lines.extend(_case_details(row))
    return "\n".join(lines).strip() + "\n"


def _summary_row(row: dict[str, Any]) -> str:
    return (
        f"| `{row['id']}` | {row['status_code']} | "
        f"`{row['fallback_mode']}` | "
        f"{_number(row['answer_usefulness_score'])} | "
        f"{_number(row['expected_point_recall'])} | "
        f"{_number(row['source_relevance_score'])} | "
        f"{_number(row['citation_relevance_score'])} | "
        f"{_number(row['provider_quality_score'])} | "
        f"{row['off_topic_source_count']} | {row['ineligible_citation_count']} | "
        f"`{row['adapter_mode']}` | "
        f"`{row['vector_backend']}` | {row['latency_ms']} ms | "
        f"`{row['failure_reason']}` |"
    )


def _case_details(row: dict[str, Any]) -> list[str]:
    lines = [f"### `{row['id']}`", "", f"URL: {row['url']}", ""]
    lines.extend([f"Fallback: `{row['fallback_mode']}`", ""])
    for index, bullet in enumerate(row["bullets"], start=1):
        item = _mapping(bullet)
        source_ids = ", ".join(str(source) for source in _list(item.get("source_ids")))
        lines.append(f"{index}. {item.get('text', '')} (`{source_ids}`)")
    lines.extend(["", "Sources:"])
    for source in row["sources"][:6]:
        item = _mapping(source)
        lines.append(
            f"- `{item.get('id')}` {item.get('title')} - {item.get('url')} "
            f"(`{item.get('domain')}`, quality={_number(item.get('quality_score'))}, "
            f"eligible={item.get('citation_eligible')})"
        )
    warnings = row.get("warnings", [])
    lines.extend(["", "Warnings:"])
    if warnings:
        for warning in warnings[:10]:
            lines.append(f"- `{warning}`")
    else:
        lines.append("- none")
    lines.append("")
    return lines


def _source_summary(source: Any) -> dict[str, Any]:
    item = _mapping(source)
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "url": item.get("url"),
        "domain": urlparse(str(item.get("url", ""))).netloc.lower() or "not_reported",
        "type": item.get("type"),
        "snippet": item.get("snippet"),
        "quality_score": item.get("quality_score"),
        "citation_eligible": item.get("citation_eligible"),
    }


def _number(value: Any) -> str:
    return f"{float(value):.3f}" if isinstance(value, (int, float)) else "0.000"


def _is_json_response(response: Any) -> bool:
    return "json" in response.headers.get("content-type", "").lower()


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write live API quality review.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--max-cases", type=int, default=10)
    parser.add_argument("--min-passes", type=int, default=8)
    parser.add_argument("--no-enforce", action="store_true")
    return parser.parse_args(argv)


def main() -> None:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is required to write the live quality review.")
    args = parse_args()
    client = TestClient(create_app())
    rows = [run_case(client, case, api_key) for case in public_cases(args.cases, args.max_cases)]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_markdown(rows), encoding="utf-8")
    failures = live_quality_failures(rows, min_passes=args.min_passes)
    print(json.dumps({"path": str(args.out), "cases": len(rows)}, indent=2))
    if failures["blocking_failures"] and not args.no_enforce:
        message = ", ".join(str(item) for item in failures["blocking_failures"])
        raise SystemExit(f"live quality review failed: {message}")


if __name__ == "__main__":
    main()
