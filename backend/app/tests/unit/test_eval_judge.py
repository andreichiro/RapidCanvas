from __future__ import annotations

import pytest

from app.config import Settings
from app.eval.judge import DeterministicJudge, DspyJudge, RagasJudge
from app.tests.unit.test_eval_metrics import make_case, make_fixture


def test_deterministic_judge_scores_cached_fixture() -> None:
    result = DeterministicJudge().score(make_case(), make_fixture())

    assert result["judge_backend"] == "deterministic"
    assert result["judge_expected_support"] == 1.0
    assert result["judge_evidence_selection"] == 1.0
    assert result["judge_safety"] == 1.0


def test_dspy_judge_executes_injected_program() -> None:
    calls: list[dict[str, str]] = []

    def program(**kwargs: str) -> dict[str, float]:
        calls.append(kwargs)
        return {"expected_support": 0.7, "evidence_selection": 0.6, "safety": 0.5}

    result = DspyJudge(program=program).score(make_case(), make_fixture())

    assert calls
    assert result["dspy_judge_backend"] == "dspy"
    assert result["dspy_judge_expected_support"] == 0.7
    assert result["dspy_judge_evidence_selection"] == 0.6
    assert result["dspy_judge_safety"] == 0.5


def test_ragas_judge_executes_injected_evaluator() -> None:
    calls: list[dict[str, object]] = []

    def evaluate(row: dict[str, object]) -> dict[str, float]:
        calls.append(row)
        return {"faithfulness": 0.4, "context_precision": 0.3, "context_recall": 0.2}

    result = RagasJudge(evaluate_fn=evaluate).score(make_case(), make_fixture())

    assert calls
    assert result["ragas_backend"] == "ragas"
    assert result["ragas_faithfulness"] == 0.4
    assert result["ragas_context_precision"] == 0.3
    assert result["ragas_context_recall"] == 0.2


def test_dspy_judge_runs_offline_dspy_program_when_available() -> None:
    pytest.importorskip("dspy")

    result = DspyJudge(settings=Settings(openai_api_key=None)).score(make_case(), make_fixture())

    assert result["dspy_judge_backend"] == "dspy"
    assert 0.0 <= float(result["dspy_judge_expected_support"]) <= 1.0
    assert 0.0 <= float(result["dspy_judge_evidence_selection"]) <= 1.0
    assert result["dspy_judge_safety"] == 1.0


def test_ragas_judge_runs_offline_ragas_metrics_when_available() -> None:
    pytest.importorskip("datasets")
    pytest.importorskip("ragas")
    pytest.importorskip("rapidfuzz")

    result = RagasJudge(settings=Settings(openai_api_key=None)).score(make_case(), make_fixture())

    assert result["ragas_backend"] == "ragas"
    assert result["ragas_mode"] == "ragas_non_llm_offline"
    assert 0.0 <= float(result["ragas_faithfulness"]) <= 1.0
    assert 0.0 <= float(result["ragas_context_precision"]) <= 1.0
    assert 0.0 <= float(result["ragas_context_recall"]) <= 1.0
