"""Command-line evaluation runner."""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from app.eval.agents import CachePolicy, EvalAgent, build_eval_agent
from app.eval.dataset import (
    DEFAULT_CASES_PATH,
    REPO_ROOT,
    load_eval_cases,
    resolve_repo_path,
)
from app.eval.judge import EvalJudge, build_judge, judge_case
from app.eval.metrics import aggregate_scores, score_case
from app.eval.report import fallback_counts, write_reports

DEFAULT_OUTPUT_DIR = REPO_ROOT / "reports" / "eval"


def run_eval(
    cases_path: Path = DEFAULT_CASES_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    mode: str = "cached",
    judge_name: str = "deterministic",
    cache_policy: CachePolicy = "none",
    parallelism: int = 1,
    agent: EvalAgent | None = None,
    judge: EvalJudge | None = None,
) -> dict[str, Any]:
    """Run eval cases through an agent and write report artifacts."""

    active_judge = judge or build_judge(judge_name)
    cases = load_eval_cases(cases_path)
    rows: list[dict[str, Any]] = []
    fixtures = _predict_fixtures(cases, mode, cache_policy, parallelism, agent)
    for case, fixture in zip(cases, fixtures, strict=True):
        row = score_case(case, fixture)
        row.update(judge_case(case, fixture, active_judge))
        rows.append(row)

    summary: dict[str, Any] = aggregate_scores(rows)
    summary.update(_run_metadata(mode, judge_name, len(rows)))
    summary.update(_case_coverage_metadata(cases, mode))
    summary.update(_optional_tool_status(mode, judge_name))
    summary.update(_cache_policy_metadata(rows, cache_policy, mode))
    summary["fallback_modes"] = fallback_counts(rows)
    paths = write_reports(rows, summary, resolve_repo_path(output_dir))
    return {
        "rows": rows,
        "summary": summary,
        "paths": {key: str(value) for key, value in paths.items()},
    }


def _predict_fixtures(
    cases: list[Any],
    mode: str,
    cache_policy: CachePolicy,
    parallelism: int,
    agent: EvalAgent | None,
) -> list[Any]:
    if agent is not None or mode != "api" or parallelism <= 1:
        active_agent = agent or build_eval_agent(mode, cache_policy=cache_policy)
        return [active_agent.predict(case) for case in cases]
    worker_count = max(1, min(parallelism, len(cases)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        return list(
            executor.map(
                lambda case: build_eval_agent(mode, cache_policy=cache_policy).predict(case),
                cases,
            )
        )


def _run_metadata(mode: str, judge_name: str, row_count: int) -> dict[str, float | str | bool]:
    api_mode = mode == "api"
    model_judge = judge_name in {"dspy", "ragas", "composite"}
    cached_predictions = mode in {"cached", "fake-agent"}
    return {
        "prediction_mode": mode,
        "judge_backend": judge_name,
        "case_count": float(row_count),
        "cached_case_count": float(row_count if cached_predictions else 0),
        "api_attempted_case_count": float(row_count if api_mode else 0),
        "api_network_calls_allowed": api_mode,
        "model_judge_calls_allowed": model_judge,
    }


def _case_coverage_metadata(cases: list[Any], mode: str) -> dict[str, float | str | bool]:
    public_fixture_count = sum(1 for case in cases if case.is_public_fixture)
    synthetic_count = sum(1 for case in cases if case.provenance == "synthetic_fixture")
    verified_count = sum(1 for case in cases if case.is_public_fixture and case.live_verified_at)
    cached_fixture_count = sum(1 for case in cases if case.fixture_paths)
    return {
        "public_fixture_case_count": float(public_fixture_count),
        "synthetic_fixture_case_count": float(synthetic_count),
        "live_verified_public_case_count": float(verified_count),
        "cached_fixture_available_count": float(cached_fixture_count),
        "public_bluesky_fixture_case_count": float(public_fixture_count),
        "public_case_coverage_status": (
            "fixture_backed_public_urls"
            if public_fixture_count >= 10
            else "insufficient_public_fixture_coverage"
        ),
        "live_pipeline_quality_status": (
            "api_mode_live_route"
            if mode == "api"
            else "cached_reproducibility_run"
        ),
    }


def _optional_tool_status(mode: str, judge_name: str) -> dict[str, str]:
    dspy_ran = judge_name in {"dspy", "composite"}
    ragas_ran = judge_name in {"ragas", "composite"}
    dspy_skip = (
        "Default eval prediction can run live, but the default judge remains "
        "deterministic/no-network; run --judge dspy with backend ai extras to execute "
        "the DSPy judge."
    )
    ragas_skip = (
        "Default eval prediction can run live, but the default judge remains "
        "deterministic/no-network; run --judge ragas with backend eval extras to execute "
        "Ragas metrics."
    )
    mlflow_skip = (
        "MLflow logging is intentionally isolated behind make mlflow-log so eval "
        "does not create mlruns artifacts."
    )
    return {
        "dspy_judge_status": "ran" if dspy_ran else "skipped",
        "dspy_judge_skip_reason": "" if dspy_ran else dspy_skip,
        "ragas_status": "ran" if ragas_ran else "skipped",
        "ragas_skip_reason": "" if ragas_ran else ragas_skip,
        "ragas_metric_source": "ragas_judge" if ragas_ran else "deterministic_proxy",
        "mlflow_status": "not_run_by_make_eval",
        "mlflow_skip_reason": mlflow_skip,
    }


def _cache_policy_metadata(
    rows: list[dict[str, Any]],
    cache_policy: CachePolicy,
    mode: str,
) -> dict[str, float | str]:
    fallback_count = sum(
        1 for row in rows if float(row.get("exact_post_cache_fallback", 0.0)) > 0
    )
    live_success_count = _live_prediction_success_count(rows, mode)
    return {
        "cache_policy": cache_policy,
        "exact_post_cache_fallback_count": float(fallback_count),
        "live_case_count": float(live_success_count),
        "live_prediction_success_count": float(live_success_count),
    }


def _live_prediction_success_count(rows: list[dict[str, Any]], mode: str) -> int:
    if mode != "api":
        return 0
    return sum(1 for row in rows if _live_prediction_succeeded(row))


def _live_prediction_succeeded(row: dict[str, Any]) -> bool:
    if float(row.get("exact_post_cache_fallback", 0.0)) > 0:
        return False
    return str(row.get("predicted_category", "")) != "api_error"


def run_cached_eval(
    cases_path: Path = DEFAULT_CASES_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    """Run cached eval fixtures and write report artifacts."""

    return run_eval(cases_path=cases_path, output_dir=output_dir)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Bluesky explainer eval cases.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--mode", choices=["cached", "fake-agent", "api"], default="cached")
    parser.add_argument("--cache-policy", choices=["none", "exact-post"], default="none")
    parser.add_argument("--parallelism", type=int, default=1)
    parser.add_argument("--require-live-key", action="store_true")
    parser.add_argument(
        "--judge",
        choices=["deterministic", "dspy", "ragas", "composite"],
        default="deterministic",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.require_live_key and args.mode == "api" and not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required for default live eval.")
    result = run_eval(
        args.cases,
        args.out,
        mode=args.mode,
        judge_name=args.judge,
        cache_policy=args.cache_policy,
        parallelism=args.parallelism,
    )
    print(
        json.dumps(
            {"summary": result["summary"], "paths": result["paths"]},
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
