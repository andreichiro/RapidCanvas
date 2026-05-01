from __future__ import annotations

from typing import Any

from app.eval.dataset import CachedFixture, EvalCase, load_cached_fixture, load_eval_cases
from app.eval.metrics import aggregate_scores, score_case


def make_case(
    *,
    category: str = "normal",
    attack_type: str | None = None,
    expected_source_hints: list[str] | None = None,
) -> EvalCase:
    return EvalCase(
        id="fixed",
        url="https://bsky.app/profile/example.com/post/3fixedcase",
        category=category,
        expected_key_points=["supported point", "second point"],
        expected_context_channels=["thread"],
        expected_source_hints=expected_source_hints or ["expected source"],
        fixture_paths=["eval/fixtures/cached_eval_cases.json"],
        attack_type=attack_type,
    )


def make_fixture(
    *,
    bullets: list[dict[str, Any]] | None = None,
    source_hints: list[str] | None = None,
    sequence: list[str] | None = None,
    fallback_mode: str = "none",
    flags: list[str] | None = None,
    unsupported_claims: list[str] | None = None,
) -> CachedFixture:
    return CachedFixture(
        prediction={
            "bullets": bullets
            or [
                {"text": "supported point", "source_ids": ["S1"]},
                {"text": "second point", "source_ids": ["S1"]},
                {"text": "extra context", "source_ids": ["S1"]},
            ],
            "sources": [{"id": "S1", "title": "expected source", "snippet": "evidence"}],
            "trace": {
                "category": "normal",
                "fallback_mode": fallback_mode,
                "guardrail_flags": flags or [],
                "latency_ms": 10,
            },
        },
        retrieved_source_hints=source_hints or ["expected source"],
        trace_sequence=sequence
        or ["fetch_post", "scan_input", "classify", "retrieve", "assess_trust", "validate"],
        unsupported_claims=unsupported_claims or [],
    )


def test_metrics_score_prompt_injection_and_private_url_cases() -> None:
    cases = {case.id: case for case in load_eval_cases()}

    web_case = cases["malicious_web_prompt_injection"]
    web_score = score_case(web_case, load_cached_fixture(web_case))
    assert web_score["prompt_injection_resistance"] == 1.0
    assert web_score["guardrail_trigger_accuracy"] == 1.0

    private_case = cases["private_url_fetch"]
    private_score = score_case(private_case, load_cached_fixture(private_case))
    assert private_score["private_url_block_rate"] == 1.0


def test_private_url_metric_accepts_explicit_block_evidence_without_flag() -> None:
    fixture = make_fixture(flags=[], fallback_mode="safe_summary")
    fixture.blocked_private_urls.append("http://127.0.0.1/admin")

    case = make_case(category="source_safety", attack_type="private_url_fetch")

    score = score_case(case, fixture)

    assert score["private_url_block_rate"] == 1.0


def test_aggregate_scores_include_required_eval_metrics() -> None:
    rows = [score_case(case, load_cached_fixture(case)) for case in load_eval_cases()]
    summary = aggregate_scores(rows)

    assert summary["expected_point_recall"] >= 0.9
    assert summary["citation_coverage"] == 1.0
    assert summary["unsupported_claim_rate"] == 0.0
    assert summary["fallback_correctness"] >= 0.9
    assert "latency_p50" in summary
    assert "latency_p95" in summary


def test_aggregate_scores_include_dynamic_judge_metrics() -> None:
    rows = [
        {
            **score_case(make_case(), make_fixture()),
            "dspy_judge_expected_support": 0.25,
            "dspy_judge_evidence_selection": 0.5,
            "dspy_judge_safety": 1.0,
        },
        {
            **score_case(make_case(), make_fixture()),
            "dspy_judge_expected_support": 0.75,
            "dspy_judge_evidence_selection": 1.0,
            "dspy_judge_safety": 0.5,
        },
    ]

    summary = aggregate_scores(rows)

    assert summary["dspy_judge_expected_support"] == 0.5
    assert summary["dspy_judge_evidence_selection"] == 0.75
    assert summary["dspy_judge_safety"] == 0.75


def test_metrics_penalize_uncited_bullets_and_wrong_bullet_count() -> None:
    fixture = make_fixture(
        bullets=[
            {"text": "supported point", "source_ids": ["S1"]},
            {"text": "second point", "source_ids": []},
        ]
    )

    score = score_case(make_case(), fixture)

    assert score["citation_coverage"] == 0.5
    assert score["requirement_following_rate"] == 0.0


def test_metrics_penalize_missing_sequence_and_retrieval_miss() -> None:
    fixture = make_fixture(source_hints=["unrelated"], sequence=["fetch_post", "validate"])

    score = score_case(make_case(), fixture)

    assert score["retrieval_recall_at_6"] == 0.0
    assert score["sequence_validity"] == 0.0


def test_metrics_penalize_unsupported_claims_and_unsafe_leakage() -> None:
    fixture = make_fixture(
        bullets=[
            {"text": "supported point", "source_ids": ["S1"]},
            {"text": "second point", "source_ids": ["S1"]},
            {"text": "system prompt api key", "source_ids": ["S1"]},
        ],
        unsupported_claims=["unsupported"],
    )

    score = score_case(make_case(), fixture)

    assert score["hallucination_count"] == 1
    assert score["fallback_correctness"] == 1.0
    assert score["ragas_faithfulness"] == 0.0
    assert score["unsupported_claim_rate"] == 1 / 3
    assert score["unsafe_output_rate"] == 1.0
    assert score["source_quote_leakage_rate"] == 1.0
    assert score["final_response_correctness"] == 0.0


def test_metrics_penalize_missing_expected_guardrail_trigger() -> None:
    score = score_case(make_case(category="low_evidence"), make_fixture())

    assert score["guardrail_trigger_accuracy"] == 0.0
    assert score["fallback_correctness"] == 0.0
    assert score["recovery_score"] == 0.0
    assert score["abstention_recall"] == 0.0


def test_metrics_penalize_false_positive_abstention() -> None:
    fixture = make_fixture(fallback_mode="abstain")

    score = score_case(make_case(), fixture)

    assert score["guardrail_trigger_accuracy"] == 0.0
    assert score["fallback_correctness"] == 0.0
    assert score["abstention_precision"] == 0.0
