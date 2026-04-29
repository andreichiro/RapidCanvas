"""Command-line cached evaluation runner."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.eval.dataset import (
    DEFAULT_CASES_PATH,
    REPO_ROOT,
    load_cached_fixture,
    load_eval_cases,
    resolve_repo_path,
)
from app.eval.judge import judge_case
from app.eval.metrics import aggregate_scores, score_case
from app.eval.report import fallback_counts, write_reports

DEFAULT_OUTPUT_DIR = REPO_ROOT / "reports" / "eval"


def run_cached_eval(
    cases_path: Path = DEFAULT_CASES_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    """Run cached eval fixtures and write report artifacts."""

    rows: list[dict[str, Any]] = []
    for case in load_eval_cases(cases_path):
        fixture = load_cached_fixture(case)
        row = score_case(case, fixture)
        row.update(judge_case(case, fixture))
        rows.append(row)

    summary: dict[str, Any] = aggregate_scores(rows)
    summary["case_count"] = float(len(rows))
    summary["cached_case_count"] = float(len(rows))
    summary["fallback_modes"] = fallback_counts(rows)
    paths = write_reports(rows, summary, resolve_repo_path(output_dir))
    return {
        "rows": rows,
        "summary": summary,
        "paths": {key: str(value) for key, value in paths.items()},
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run cached Bluesky explainer eval fixtures.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--mode", choices=["cached"], default="cached")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_cached_eval(args.cases, args.out)
    print(
        json.dumps(
            {"summary": result["summary"], "paths": result["paths"]},
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
