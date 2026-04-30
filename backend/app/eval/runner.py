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
    rows: list[dict[str, Any]] = []
    for case in load_eval_cases(cases_path):
        fixture = active_agent.predict(case)
        row = score_case(case, fixture)
        row.update(judge_case(case, fixture, active_judge))
        rows.append(row)

    summary: dict[str, Any] = aggregate_scores(rows)
    summary.update(_run_metadata(mode, judge_name, len(rows)))
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
