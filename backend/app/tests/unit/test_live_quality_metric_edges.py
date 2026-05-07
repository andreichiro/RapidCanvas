from __future__ import annotations

from typing import Any

from app.eval.dataset import CachedFixture, EvalCase
from app.eval.metrics import score_case


def _case() -> EvalCase:
    return EvalCase(
        id="quality_edge",
        url="https://bsky.app/profile/example.com/post/3qualityedge",
        category="normal",
        expected_key_points=["agency announced rule", "deadline changed"],
        expected_context_channels=["web"],
        expected_source_hints=["official expected source"],
        fixture_paths=["eval/fixtures/cached_eval_cases.json"],
        provenance="fixture_backed_public",
    )


def _fixture(
    *,
    bullets: list[dict[str, Any]] | None = None,
    sources: list[dict[str, Any]],
) -> CachedFixture:
    return CachedFixture(
        prediction={
            "bullets": bullets
            or [
                {"text": "The agency announced a rule.", "source_ids": ["S1"]},
                {"text": "The deadline changed.", "source_ids": ["S1"]},
                {"text": "The answer cites the agency source.", "source_ids": ["S1"]},
            ],
            "sources": sources,
            "trace": {
                "category": "normal",
                "fallback_mode": "none",
                "adapter_mode": "none",
                "guardrail_flags": [],
                "latency_ms": 10,
            },
        },
        retrieved_source_hints=["official expected source"],
        trace_sequence=[
            "fetch_post",
            "scan_input",
            "classify",
            "retrieve",
            "assess_trust",
            "validate",
        ],
        unsupported_claims=[],
    )


def test_public_pass_fails_when_cited_source_is_explicitly_ineligible() -> None:
    fixture = _fixture(
        sources=[
            {
                "id": "S1",
                "title": "official expected source",
                "type": "web",
                "url": "https://expected.example.test/source",
                "snippet": (
                    "agency announced rule deadline changed official expected source evidence"
                ),
                "citation_eligible": False,
                "quality_score": 1.0,
            }
        ],
    )

    score = score_case(_case(), fixture)

    assert score["citation_coverage"] == 1.0
    assert score["ineligible_citation_count"] == 1
    assert score["public_live_quality_pass"] == 0.0


def test_runtime_quality_boost_is_limited_for_marginal_overlap_sources() -> None:
    fixture = _fixture(
        sources=[
            {
                "id": "S1",
                "title": "General discussion",
                "type": "web",
                "url": "https://general.example.test/story",
                "snippet": (
                    "An agency overview in a long unrelated document about a different topic "
                    "with no relevant event details."
                ),
                "quality_score": 1.0,
            }
        ],
    )

    score = score_case(_case(), fixture)

    assert float(score["source_relevance_score"]) < 0.4
    assert score["public_live_quality_pass"] == 0.0


def test_prompt_injection_source_metadata_is_ineligible() -> None:
    fixture = _fixture(
        sources=[
            {
                "id": "S1",
                "title": "official expected source",
                "type": "web",
                "url": "https://expected.example.test/source",
                "snippet": (
                    "agency announced rule deadline changed official expected source evidence"
                ),
                "metadata": {"prompt_injection_flags": ["ignore_previous"]},
                "quality_score": 1.0,
            }
        ],
    )

    score = score_case(_case(), fixture)

    assert score["ineligible_citation_count"] == 1
    assert score["citation_relevance_score"] == 0.0
    assert score["public_live_quality_pass"] == 0.0


def test_failed_fetch_source_metadata_is_ineligible() -> None:
    fixture = _fixture(
        sources=[
            {
                "id": "S1",
                "title": "official expected source",
                "type": "web",
                "url": "https://expected.example.test/source",
                "snippet": (
                    "agency announced rule deadline changed official expected source evidence"
                ),
                "metadata": {"fetch_success": False, "fetch_status": 403},
                "quality_score": 1.0,
            }
        ],
    )

    score = score_case(_case(), fixture)

    assert score["ineligible_citation_count"] == 1
    assert score["source_relevance_score"] == 0.0
    assert score["public_live_quality_pass"] == 0.0


def test_uncited_catalog_source_is_not_counted_as_off_topic_citation() -> None:
    fixture = _fixture(
        sources=[
            {
                "id": "S1",
                "title": "official expected source",
                "type": "web",
                "url": "https://expected.example.test/source",
                "snippet": (
                    "agency announced rule deadline changed official expected source evidence"
                ),
                "quality_score": 1.0,
            },
            {
                "id": "S2",
                "title": "Trading card marketplace catalog",
                "type": "web",
                "url": "https://cards.example.test/catalog",
                "snippet": "Buy graded rookie cards with coupons and marketplace listings.",
            },
        ],
    )

    score = score_case(_case(), fixture)

    assert score["off_topic_source_count"] == 0
    assert float(score["source_relevance_score"]) > 0.9
    assert float(score["citation_relevance_score"]) > 0.0
    assert score["public_live_quality_pass"] == 1.0


def test_provider_default_warning_fails_provider_quality() -> None:
    fixture = _fixture(
        sources=[
            {
                "id": "S1",
                "title": "official expected source",
                "type": "web",
                "url": "https://expected.example.test/source",
                "snippet": (
                    "agency announced rule deadline changed official expected source evidence"
                ),
            }
        ],
    )
    fixture.prediction["trace"]["warnings"] = [
        "provider_gemini_skipped:GEMINI_API_KEY is not configured",
        "provider_openai_default_used",
    ]

    score = score_case(_case(), fixture)

    assert score["provider_quality_score"] == 0.0
    assert score["public_live_quality_pass"] == 0.0
