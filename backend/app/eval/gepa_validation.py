"""Validation helpers for GEPA real optimization runs."""

from __future__ import annotations

from typing import Any


def gepa_success_stats(compiled: Any, optimizer: Any) -> dict[str, Any]:
    """Fail real GEPA runs when all rollouts stayed at the failure score."""

    details = getattr(compiled, "detailed_results", None)
    if details is None:
        return {
            "best_validation_score": None,
            "total_metric_calls": None,
            "num_full_val_evals": None,
        }
    scores = [float(score) for score in getattr(details, "val_aggregate_scores", [])]
    if not scores:
        raise RuntimeError("GEPA --real produced no validation scores.")
    best_score = max(scores)
    failure_score = float(getattr(optimizer, "failure_score", 0.0))
    if best_score <= failure_score:
        raise RuntimeError(
            "GEPA --real produced no successful validation rollouts. "
            "Check provider credentials and model access before saving a real program."
        )
    return {
        "best_validation_score": best_score,
        "total_metric_calls": getattr(details, "total_metric_calls", None),
        "num_full_val_evals": getattr(details, "num_full_val_evals", None),
    }
