"""Ragas, DSPy, and deterministic judge backends for eval rows."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any, Protocol, cast

from app.eval.dataset import CachedFixture, EvalCase
from app.eval.metrics import expected_point_recall, retrieval_recall


class MissingJudgeDependency(RuntimeError):
    """Raised when an explicit optional judge backend cannot run."""


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

    def __init__(self, program: Callable[..., object] | None = None) -> None:
        self._program = program

    def score(self, case: EvalCase, fixture: CachedFixture) -> dict[str, float | str]:
        program = self._program or _build_dspy_program()
        result = program(
            expected="\n".join(case.expected_key_points),
            prediction=_prediction_text(fixture),
            evidence="\n".join(fixture.retrieved_source_hints),
        )
        return {
            "dspy_judge_backend": self.backend_name,
            "dspy_judge_expected_support": _score_value(result, "expected_support"),
            "dspy_judge_evidence_selection": _score_value(result, "evidence_selection"),
            "dspy_judge_safety": _score_value(result, "safety"),
        }


class RagasJudge:
    """Ragas-backed judge for faithfulness and context metrics."""

    backend_name = "ragas"

    def __init__(
        self,
        evaluate_fn: Callable[[dict[str, object]], object] | None = None,
    ) -> None:
        self._evaluate_fn = evaluate_fn

    def score(self, case: EvalCase, fixture: CachedFixture) -> dict[str, float | str]:
        evaluate_fn = self._evaluate_fn or _build_ragas_evaluate_fn()
        row: dict[str, object] = {
            "user_input": case.url,
            "response": _prediction_text(fixture),
            "retrieved_contexts": fixture.retrieved_source_hints,
            "reference": "\n".join(case.expected_key_points),
        }
        result = evaluate_fn(row)
        return {
            "ragas_backend": self.backend_name,
            "ragas_faithfulness": _result_value(result, ("faithfulness", "ragas_faithfulness")),
            "ragas_context_precision": _result_value(
                result,
                ("context_precision", "llm_context_precision_with_reference"),
            ),
            "ragas_context_recall": _result_value(result, ("context_recall", "llm_context_recall")),
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


def _build_dspy_program() -> Callable[..., object]:
    try:
        dspy = importlib.import_module("dspy")
    except ImportError as exc:
        raise MissingJudgeDependency("Install the backend ai extra to use --judge dspy.") from exc

    class JudgeEvaluationCase(dspy.Signature):  # type: ignore[name-defined]
        """Score whether prediction matches expected points and evidence safely."""

        expected: str = dspy.InputField()
        prediction: str = dspy.InputField()
        evidence: str = dspy.InputField()
        expected_support: float = dspy.OutputField()
        evidence_selection: float = dspy.OutputField()
        safety: float = dspy.OutputField()

    return cast(Callable[..., object], dspy.Predict(JudgeEvaluationCase))


def _build_ragas_evaluate_fn() -> Callable[[dict[str, object]], object]:
    try:
        datasets = importlib.import_module("datasets")
        ragas = importlib.import_module("ragas")
        ragas_metrics = importlib.import_module("ragas.metrics")
    except ImportError as exc:
        raise MissingJudgeDependency(
            "Install the backend eval extra to use --judge ragas."
        ) from exc

    metric_classes = [
        "Faithfulness",
        "LLMContextPrecisionWithReference",
        "LLMContextRecall",
    ]
    metrics = []
    for class_name in metric_classes:
        metric_class = getattr(ragas_metrics, class_name, None)
        if metric_class is not None:
            metrics.append(metric_class())
    if not metrics:
        raise MissingJudgeDependency("Installed Ragas package did not expose required metrics.")

    def evaluate(row: dict[str, object]) -> object:
        dataset = datasets.Dataset.from_list([row])
        return ragas.evaluate(dataset, metrics=metrics)

    return evaluate


def _prediction_text(fixture: CachedFixture) -> str:
    bullets = fixture.prediction.get("bullets", [])
    if not isinstance(bullets, list):
        return ""
    return "\n".join(str(bullet.get("text", "")) for bullet in bullets if isinstance(bullet, dict))


def _score_value(result: object, key: str) -> float:
    if isinstance(result, dict):
        return _coerce_float(result.get(key, 0.0))
    return _coerce_float(getattr(result, key, 0.0))


def _result_value(result: object, aliases: tuple[str, ...]) -> float:
    if hasattr(result, "to_pandas"):
        frame = result.to_pandas()
        row = frame.iloc[0].to_dict()
        return _dict_value(row, aliases)
    if isinstance(result, dict):
        return _dict_value(result, aliases)
    return 0.0


def _dict_value(result: dict[str, object], aliases: tuple[str, ...]) -> float:
    for alias in aliases:
        if alias in result:
            return _coerce_float(result[alias])
    return 0.0


def _coerce_float(value: object) -> float:
    if isinstance(value, list | tuple):
        value = value[0] if value else 0.0
    try:
        return float(cast(Any, value))
    except (TypeError, ValueError):
        return 0.0
