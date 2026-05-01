from __future__ import annotations

from pathlib import Path

from app.eval.dataset import load_cached_fixture, load_eval_cases
from app.eval.runner import run_eval

REQUIRED_CATEGORIES = {
    "niche_reference",
    "meme_slang",
    "current_event",
    "reply_context",
    "quote_context",
    "link_context",
    "image_context",
    "ambiguous_acronym",
    "adversarial_false_premise",
    "sparse_context",
    "non_english",
    "unavailable_deleted",
    "prompt_injection_web",
    "prompt_injection_bluesky",
    "prompt_injection_image_alt",
    "contradictory_sources",
    "low_evidence",
    "source_safety",
}
REQUIRED_SUMMARY_METRICS = {
    "expected_point_recall",
    "citation_coverage",
    "hallucination_count",
    "unsupported_claim_rate",
    "fallback_correctness",
    "prompt_injection_resistance",
    "private_url_block_rate",
    "latency_p50",
    "latency_p95",
}
REQUIRED_POST_KEYS = {"url", "author", "text", "created_at"}
REQUIRED_SOURCE_KEYS = {"id", "title", "url", "type", "snippet"}
REQUIRED_TRACE_KEYS = {
    "category",
    "queries",
    "warnings",
    "latency_ms",
    "trust_score",
    "fallback_mode",
    "guardrail_flags",
    "adapter_mode",
}


def test_gate6_eval_case_mix_and_public_fixture_honesty() -> None:
    cases = load_eval_cases()
    public_cases = [case for case in cases if case.is_public_fixture]
    synthetic_cases = [case for case in cases if case.provenance == "synthetic_fixture"]

    assert len(cases) >= 12
    assert len(public_cases) >= 10
    assert len([case for case in cases if case.fixture_paths]) >= 10
    assert {case.category for case in cases} >= REQUIRED_CATEGORIES
    assert not any(case.is_public_fixture and "example.com" in case.url for case in cases)

    for case in public_cases:
        assert "bsky.app/profile/" in case.url
        assert case.live_verified_at
        assert case.live_verification_method
        assert case.limitations
        assert "eval/fixtures/gate6/public_cases.json" in case.fixture_paths

    for case in synthetic_cases:
        assert case.limitations
        if "example.com" in case.url:
            assert not case.is_public_fixture


def test_gate6_cached_fixture_shape_matches_api_and_trace_contracts() -> None:
    for case in load_eval_cases():
        fixture = load_cached_fixture(case)
        prediction = fixture.prediction
        post = prediction.get("post", {})
        sources = prediction.get("sources", [])
        bullets = prediction.get("bullets", [])
        trace = prediction.get("trace", {})

        assert set(post) >= REQUIRED_POST_KEYS
        assert 3 <= len(bullets) <= 5
        assert sources
        assert all(set(source) >= REQUIRED_SOURCE_KEYS for source in sources)
        assert set(trace) >= REQUIRED_TRACE_KEYS
        assert fixture.trace_sequence

        source_ids = {source["id"] for source in sources}
        assert all(set(bullet.get("source_ids", [])) <= source_ids for bullet in bullets)
        assert all(bullet.get("source_ids") for bullet in bullets)

        if case.is_public_fixture:
            assert "gate6_cached_public_fixture_not_live_refetch" in trace["warnings"]
            assert trace["adapter_mode"] == "none"
        else:
            assert trace["adapter_mode"] == "deterministic_dev"


def test_gate6_report_summary_and_artifacts_are_reviewer_ready(tmp_path: Path) -> None:
    result = run_eval(output_dir=tmp_path)
    summary = result["summary"]
    paths = {name: Path(path) for name, path in result["paths"].items()}

    assert set(summary) >= REQUIRED_SUMMARY_METRICS
    assert summary["case_count"] == 19.0
    assert summary["public_fixture_case_count"] == 10.0
    assert summary["public_bluesky_fixture_case_count"] == 10.0
    assert summary["live_verified_public_case_count"] == 10.0
    assert summary["synthetic_fixture_case_count"] == 9.0
    assert summary["public_case_coverage_status"] == "fixture_backed_public_urls"
    assert summary["ragas_metric_source"] == "deterministic_proxy"
    assert summary["ragas_status"] == "skipped"
    assert summary["dspy_judge_status"] == "skipped"
    assert summary["mlflow_status"] == "not_run_by_make_eval"
    assert "final_public_bluesky_case_count" not in summary

    assert paths["jsonl"].read_text(encoding="utf-8").count("\n") == 19
    report = paths["markdown"].read_text(encoding="utf-8")
    assert report.startswith("# Bluesky Explainer Eval Report")
    assert paths["summary"].exists()
    assert paths["confusion_matrix"].exists()
    assert paths["graph"].exists()
