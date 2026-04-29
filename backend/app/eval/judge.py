"""Deterministic judge proxies for offline cached evaluation."""

from __future__ import annotations

from app.eval.dataset import CachedFixture, EvalCase
from app.eval.metrics import expected_point_recall, retrieval_recall


def judge_case(case: EvalCase, fixture: CachedFixture) -> dict[str, float]:
    """Return DSPy-judge-shaped scores without making model calls in cached mode."""

    point_recall = expected_point_recall(case, fixture.prediction)
    source_recall = retrieval_recall(case, fixture)
    unsupported = len(fixture.unsupported_claims)
    return {
        "dspy_judge_expected_support": point_recall,
        "dspy_judge_evidence_selection": source_recall,
        "dspy_judge_safety": 1.0 if unsupported == 0 else 0.0,
    }

