"""Command-line evaluation runner."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.eval.agents import EvalAgent, build_eval_agent
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
    agent: EvalAgent | None = None,
    judge: EvalJudge | None = None,
) -> dict[str, Any]:
    """Run eval cases through an agent and write report artifacts."""

    active_agent = agent or build_eval_agent(mode)
    active_judge = judge or build_judge(judge_name)
    cases = load_eval_cases(cases_path)
    rows: list[dict[str, Any]] = []
    for case in cases:
        fixture = active_agent.predict(case)
        row = score_case(case, fixture)
        row.update(judge_case(case, fixture, active_judge))
        rows.append(row)

    summary: dict[str, Any] = aggregate_scores(rows)
    summary.update(_run_metadata(mode, judge_name, len(rows)))
    summary.update(_case_coverage_metadata(cases, mode))
    summary.update(_optional_tool_status(mode, judge_name))
    summary["fallback_modes"] = fallback_counts(rows)
    paths = write_reports(rows, summary, resolve_repo_path(output_dir))
    return {
        "rows": rows,
        "summary": summary,
        "paths": {key: str(value) for key, value in paths.items()},
    }


def _run_metadata(mode: str, judge_name: str, row_count: int) -> dict[str, float | str | bool]:
    api_mode = mode == "api"
    model_judge = judge_name in {"dspy", "ragas", "composite"}
    cached_predictions = mode in {"cached", "fake-agent"}
    return {
        "prediction_mode": mode,
        "judge_backend": judge_name,
        "case_count": float(row_count),
        "cached_case_count": float(row_count if cached_predictions else 0),
        "live_case_count": float(row_count if api_mode else 0),
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
            else "not_live_default_cached_run"
        ),
    }


def _optional_tool_status(mode: str, judge_name: str) -> dict[str, str]:
    dspy_ran = judge_name in {"dspy", "composite"}
    ragas_ran = judge_name in {"ragas", "composite"}
    dspy_skip = (
        "Default make eval uses deterministic no-network judging; run --judge dspy "
        "with backend ai extras to execute the DSPy judge."
    )
    ragas_skip = (
        "Default make eval uses deterministic no-network judging; run --judge ragas "
        "with backend eval extras to execute Ragas metrics."
    )
    mlflow_skip = (
        "MLflow logging is intentionally isolated behind make mlflow-log so default "
        "eval remains offline and does not create mlruns artifacts."
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


def run_cached_eval(
    cases_path: Path = DEFAULT_CASES_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    """Run default cached eval fixtures and write report artifacts."""

    return run_eval(cases_path=cases_path, output_dir=output_dir)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run cached Bluesky explainer eval fixtures.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--mode", choices=["cached", "fake-agent", "api"], default="cached")
    parser.add_argument(
        "--judge",
        choices=["deterministic", "dspy", "ragas", "composite"],
        default="deterministic",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_eval(args.cases, args.out, mode=args.mode, judge_name=args.judge)
    print(
        json.dumps(
            {"summary": result["summary"], "paths": result["paths"]},
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
