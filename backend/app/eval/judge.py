"""Ragas, DSPy, and deterministic judge backends for eval rows."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from app.config import Settings
from app.eval.dataset import CachedFixture, EvalCase
from app.eval.judge_runtime import (
    build_dspy_program,
    build_ragas_evaluate_fn,
    prediction_text,
    result_value,
    score_value,
)
from app.eval.metrics import expected_point_recall, retrieval_recall


class EvalJudge(Protocol):
    """Evaluation judge boundary used by the runner."""

    def score(self, case: EvalCase, fixture: CachedFixture) -> dict[str, float | str]:
        """Score one case prediction."""


class DeterministicJudge:
    """Offline judge for default cached runs."""

    backend_name = "deterministic"

    def score(self, case: EvalCase, fixture: CachedFixture) -> dict[str, float | str]:
        point_recall = expected_point_recall(case, fixture.prediction)
        source_recall = retrieval_recall(case, fixture)
        unsupported = len(fixture.unsupported_claims)
        return {
            "judge_backend": self.backend_name,
            "judge_expected_support": point_recall,
            "judge_evidence_selection": source_recall,
            "judge_safety": 1.0 if unsupported == 0 else 0.0,
        }


class DspyJudge:
    """DSPy-backed judge for expected support, evidence selection, and safety."""

    backend_name = "dspy"

    def __init__(
        self,
        program: Callable[..., object] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._program = program
        self._settings = settings

    def score(self, case: EvalCase, fixture: CachedFixture) -> dict[str, float | str]:
        program = self._program or build_dspy_program(self._settings)
        result = program(
            expected="\n".join(case.expected_key_points),
            prediction=prediction_text(fixture),
            evidence="\n".join(fixture.retrieved_source_hints),
        )
        return {
            "dspy_judge_backend": self.backend_name,
            "dspy_judge_expected_support": score_value(result, "expected_support"),
            "dspy_judge_evidence_selection": score_value(result, "evidence_selection"),
            "dspy_judge_safety": score_value(result, "safety"),
        }


class RagasJudge:
    """Ragas-backed judge for faithfulness and context metrics."""

    backend_name = "ragas"

    def __init__(
        self,
        evaluate_fn: Callable[[dict[str, object]], object] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._evaluate_fn = evaluate_fn
        self._settings = settings

    def score(self, case: EvalCase, fixture: CachedFixture) -> dict[str, float | str]:
        evaluate_fn = self._evaluate_fn or build_ragas_evaluate_fn(self._settings)
        row: dict[str, object] = {
            "user_input": case.url,
            "response": prediction_text(fixture),
            "retrieved_contexts": fixture.retrieved_source_hints,
            "reference": "\n".join(case.expected_key_points),
            "reference_contexts": case.expected_source_hints or case.expected_key_points,
        }
        result = evaluate_fn(row)
        return {
            "ragas_backend": self.backend_name,
            "ragas_mode": str(result_value(result, ("ragas_mode",), default=self.backend_name)),
            "ragas_faithfulness": result_value(
                result,
                ("faithfulness", "ragas_faithfulness"),
            ),
            "ragas_context_precision": result_value(
                result,
                (
                    "context_precision",
                    "llm_context_precision_with_reference",
                    "non_llm_context_precision_with_reference",
                ),
            ),
            "ragas_context_recall": result_value(
                result,
                ("context_recall", "llm_context_recall", "non_llm_context_recall"),
            ),
        }


class CompositeJudge:
    """Run several judges and merge their scores."""

    def __init__(self, judges: list[EvalJudge]) -> None:
        self._judges = judges

    def score(self, case: EvalCase, fixture: CachedFixture) -> dict[str, float | str]:
        scores: dict[str, float | str] = {}
        for judge in self._judges:
            scores.update(judge.score(case, fixture))
        return scores


def build_judge(name: str) -> EvalJudge:
    """Build a judge backend by CLI name."""

    if name == "deterministic":
        return DeterministicJudge()
    if name == "dspy":
        return DspyJudge()
    if name == "ragas":
        return RagasJudge()
    if name == "composite":
        return CompositeJudge([DeterministicJudge(), DspyJudge(), RagasJudge()])
    raise ValueError(f"unsupported judge backend: {name}")


def judge_case(
    case: EvalCase,
    fixture: CachedFixture,
    judge: EvalJudge | None = None,
) -> dict[str, float | str]:
    """Score one eval case with the requested judge backend."""

    return (judge or DeterministicJudge()).score(case, fixture)
