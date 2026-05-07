from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


def _load_script() -> Any:
    root = Path(__file__).resolve().parents[4]
    script_path = root / "scripts" / "write_live_quality_review.py"
    spec = importlib.util.spec_from_file_location("write_live_quality_review", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _public_case() -> dict[str, Any]:
    return {
        "id": "public_quality_case",
        "url": "https://bsky.app/profile/example.com/post/3quality",
        "category": "quote_context",
        "expected_key_points": ["supported point", "second point"],
        "expected_context_channels": ["web"],
        "expected_source_hints": ["official source"],
        "fixture_paths": ["eval/fixtures/cached_eval_cases.json"],
        "provenance": "fixture_backed_public",
    }


def _payload(*, sources: list[dict[str, Any]], adapter_mode: str = "none") -> dict[str, Any]:
    return {
        "post": {
            "url": "https://bsky.app/profile/example.com/post/3quality",
            "author": "example.com",
            "text": "supported point",
            "created_at": "2026-04-29T12:00:00Z",
        },
        "bullets": [
            {"text": "supported point is explained by the official source.", "source_ids": ["S1"]},
            {"text": "second point is also covered by the same source.", "source_ids": ["S1"]},
            {"text": "extra context stays within supported point evidence.", "source_ids": ["S1"]},
        ],
        "sources": sources,
        "trace": {
            "category": "quote_context",
            "queries": ["supported point official source"],
            "warnings": ["qdrant_vector_store"],
            "latency_ms": 20,
            "trust_score": 0.9,
            "fallback_mode": "none",
            "adapter_mode": adapter_mode,
            "guardrail_flags": [],
            "adapter_notes": [],
            "vector_store_backend": "qdrant_vector_store",
        },
    }


def test_live_quality_review_runs_ten_public_cases_by_default() -> None:
    script = _load_script()

    assert len(script.public_cases(script.DEFAULT_CASES, 10)) == 10
    assert script.parse_args([]).max_cases == 10


def test_live_quality_summary_fails_off_topic_cited_source() -> None:
    script = _load_script()
    row = script.summarize_case(
        _public_case(),
        _payload(
            sources=[
                {
                    "id": "S1",
                    "title": "Trading card marketplace catalog",
                    "url": "https://cards.example.test/catalog",
                    "type": "web",
                    "snippet": "Coupon pricing for graded rookie card listings.",
                }
            ]
        ),
        200,
        31,
    )

    assert row["meaningful"] is False
    assert row["off_topic_source_count"] == 1
    assert row["failure_reason"] == "off_topic_cited_source"


def test_live_quality_report_includes_usefulness_sources_warnings_and_key_hygiene() -> None:
    script = _load_script()
    row = script.summarize_case(
        _public_case(),
        _payload(
            sources=[
                {
                    "id": "S1",
                    "title": "Official source",
                    "url": "https://official.example.test/source",
                    "type": "web",
                    "snippet": "supported point and second point official source evidence",
                }
            ]
        ),
        200,
        31,
    )

    markdown = script.render_markdown([row])

    assert "transient request key" in markdown
    assert "Fallback" in markdown
    assert "Source Rel." in markdown
    assert "Provider Q." in markdown
    assert "official.example.test" in markdown
    assert "qdrant_vector_store" in markdown
    assert "`passed`" in markdown


def test_live_quality_summary_explains_provider_quality_failure() -> None:
    script = _load_script()
    payload = _payload(
        sources=[
            {
                "id": "S1",
                "title": "Official source",
                "url": "https://official.example.test/source",
                "type": "web",
                "snippet": "supported point and second point official source evidence",
            }
        ]
    )
    payload["trace"]["warnings"] = ["dspy_provider_error"]

    row = script.summarize_case(_public_case(), payload, 200, 31)
    markdown = script.render_markdown([row])

    assert row["meaningful"] is False
    assert row["provider_quality_score"] == 0.0
    assert row["failure_reason"] == "provider_quality_failed"
    assert "| `public_quality_case` |" in markdown
    assert "Provider Q." in markdown


def test_live_quality_summary_explains_ineligible_citation_failure() -> None:
    script = _load_script()
    row = script.summarize_case(
        _public_case(),
        _payload(
            sources=[
                {
                    "id": "S1",
                    "title": "Official source",
                    "url": "https://official.example.test/source",
                    "type": "web",
                    "snippet": "supported point and second point official source evidence",
                    "citation_eligible": False,
                    "quality_score": 1.0,
                }
            ]
        ),
        200,
        31,
    )

    assert row["meaningful"] is False
    assert row["ineligible_citation_count"] == 1
    assert row["failure_reason"] == "ineligible_citation"


def test_live_quality_failure_gate_requires_eight_passes_and_reasoned_failures() -> None:
    script = _load_script()
    rows = [
        {
            "meaningful": True,
            "failure_reason": "passed",
            "off_topic_source_count": 0,
            "adapter_mode": "none",
        }
        for _ in range(7)
    ]
    rows.extend(
        [
            {
                "meaningful": False,
                "failure_reason": "low_expected_point_recall",
                "off_topic_source_count": 0,
                "adapter_mode": "none",
            },
            {
                "meaningful": False,
                "failure_reason": "low_answer_usefulness",
                "off_topic_source_count": 0,
                "adapter_mode": "none",
            },
            {
                "meaningful": False,
                "failure_reason": "abstained",
                "off_topic_source_count": 0,
                "adapter_mode": "none",
            },
        ]
    )

    failures = script.live_quality_failures(rows)

    assert failures["pass_count"] == 7
    assert failures["missing_failure_reasons"] == 0
    assert "useful_pass_count_7_below_8" in failures["blocking_failures"]


def test_live_quality_failure_gate_rejects_off_topic_or_adapter_passes() -> None:
    script = _load_script()
    rows = [
        {
            "meaningful": True,
            "failure_reason": "passed",
            "off_topic_source_count": 0,
            "adapter_mode": "none",
        }
        for _ in range(8)
    ]
    rows.append(
        {
            "meaningful": True,
            "failure_reason": "passed",
            "off_topic_source_count": 1,
            "adapter_mode": "none",
        }
    )
    rows.append(
        {
            "meaningful": True,
            "failure_reason": "passed",
            "off_topic_source_count": 0,
            "ineligible_citation_count": 0,
            "adapter_mode": "deterministic_fallback",
        }
    )

    failures = script.live_quality_failures(rows)

    assert "off_topic_passing_rows_1" in failures["blocking_failures"]
    assert "adapter_passing_rows_1" in failures["blocking_failures"]


def test_live_quality_failure_gate_rejects_ineligible_citation_passes() -> None:
    script = _load_script()
    rows = [
        {
            "meaningful": True,
            "failure_reason": "passed",
            "off_topic_source_count": 0,
            "ineligible_citation_count": 0,
            "adapter_mode": "none",
        }
        for _ in range(9)
    ]
    rows.append(
        {
            "meaningful": True,
            "failure_reason": "passed",
            "off_topic_source_count": 0,
            "ineligible_citation_count": 1,
            "adapter_mode": "none",
        }
    )

    failures = script.live_quality_failures(rows)

    assert failures["ineligible_passes"] == 1
    assert "ineligible_citation_passing_rows_1" in failures["blocking_failures"]
