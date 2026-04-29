"""GEPA optimization entry point for the DSPy explainer program."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Any

from app.agent.loader import OPTIMIZED_PROGRAM_PATH
from app.guardrails.policies import DEFAULT_POLICY


@dataclass(frozen=True)
class GepaMetricParts:
    """Inputs to the blended GEPA optimization metric."""

    expected_point_recall: float
    citation_coverage: float
    requirement_following: float
    prompt_injection_resistance: float
    fallback_correctness: float
    hallucination_count: float = 0.0
    unsupported_claim_rate: float = 0.0


@dataclass(frozen=True)
class OptimizationResult:
    """Saved-program metadata returned by dry-run and real optimization."""

    output_path: Path
    metric_score: float
    mode: str
    saved_program: dict[str, Any]


def combined_gepa_metric(parts: GepaMetricParts) -> float:
    """Blend quality, citation, safety, and fallback correctness for GEPA."""

    positive = (
        0.25 * parts.expected_point_recall
        + 0.2 * parts.citation_coverage
        + 0.18 * parts.requirement_following
        + 0.22 * parts.prompt_injection_resistance
        + 0.15 * parts.fallback_correctness
    )
    penalty = 0.18 * min(1.0, parts.hallucination_count) + 0.24 * parts.unsupported_claim_rate
    return round(max(0.0, min(1.0, positive - penalty)), 4)


def textual_feedback(missing_points: list[str], unsupported_claims: list[str]) -> str:
    """Return the feedback text passed to GEPA traces."""

    feedback: list[str] = []
    if missing_points:
        feedback.append("Missing expected points: " + "; ".join(missing_points))
    if unsupported_claims:
        feedback.append("Unsupported claims: " + "; ".join(unsupported_claims))
    return "\n".join(feedback) or "Prediction satisfies expected points and support checks."


def run_gepa_optimization(
    *,
    dry_run: bool = True,
    output_path: Path = OPTIMIZED_PROGRAM_PATH,
) -> OptimizationResult:
    """Run a fake-eval GEPA dry-run or validate the real optimizer dependency path."""

    metric_parts = GepaMetricParts(
        expected_point_recall=0.0 if dry_run else 0.5,
        citation_coverage=1.0,
        requirement_following=1.0,
        prompt_injection_resistance=1.0,
        fallback_correctness=1.0,
    )
    metric_score = combined_gepa_metric(metric_parts)
    if not dry_run:
        _require_gepa()

    saved_program = {
        "schema_version": 1,
        "optimizer": "GEPA",
        "mode": "dry_run" if dry_run else "real",
        "saved_at": datetime.now(UTC).isoformat(),
        "metric_score": metric_score,
        "metric_parts": asdict(metric_parts),
        "policy_version": DEFAULT_POLICY.version,
        "feedback_template": textual_feedback(
            ["expected contextual point absent"],
            ["claim without source support"],
        ),
        "notes": [
            "Gate 4 Dev C saves a loadable program config.",
            "Full GEPA requires Gate 9 cached eval cases before final tuning.",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(saved_program, indent=2, sort_keys=True))
    return OptimizationResult(
        output_path=output_path,
        metric_score=metric_score,
        mode=str(saved_program["mode"]),
        saved_program=saved_program,
    )


def _require_gepa() -> None:
    dspy = import_module("dspy")
    if getattr(dspy, "GEPA", None) is None and getattr(dspy, "teleprompt", None) is None:
        raise RuntimeError("DSPy GEPA optimizer is not available in this installation.")


def main(argv: list[str] | None = None) -> int:
    """CLI for ``make optimize``."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--output", default=str(OPTIMIZED_PROGRAM_PATH))
    args = parser.parse_args(argv)

    result = run_gepa_optimization(dry_run=not args.real, output_path=Path(args.output))
    print(
        json.dumps(
            {
                "output_path": str(result.output_path),
                "metric_score": result.metric_score,
                "mode": result.mode,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

