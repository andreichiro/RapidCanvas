from __future__ import annotations

import json

from pydantic import SecretStr

from app.config import Settings
from app.eval import optimize as optimize_module
from app.eval.optimize import GepaMetricParts, combined_gepa_metric, run_gepa_optimization


def test_optimizer_dry_run_saves_loadable_program(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from app.agent.loader import load_program

    output_path = tmp_path / "program.json"

    result = run_gepa_optimization(dry_run=True, output_path=output_path)
    loaded = load_program(
        Settings(openai_api_key=None),
        optimized_path=output_path,
        prefer_dspy=False,
    )

    assert result.output_path == output_path
    assert json.loads(output_path.read_text())["optimizer"] == "GEPA"
    assert loaded.optimized_path == output_path
    assert loaded.program.optimized_config["schema_version"] == 1


def test_optimizer_dry_run_is_deterministic_and_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    output_path = tmp_path / "program.json"

    run_gepa_optimization(dry_run=True, output_path=output_path)
    first_payload = output_path.read_text()
    run_gepa_optimization(dry_run=True, output_path=output_path)
    second_payload = output_path.read_text()

    assert first_payload == second_payload
    assert json.loads(second_payload)["saved_at"] == "1970-01-01T00:00:00+00:00"


def test_combined_gepa_metric_penalizes_unsupported_claims() -> None:
    strong = combined_gepa_metric(
        GepaMetricParts(
            expected_point_recall=1.0,
            citation_coverage=1.0,
            requirement_following=1.0,
            prompt_injection_resistance=1.0,
            fallback_correctness=1.0,
            unsupported_claim_rate=0.0,
        )
    )
    weak = combined_gepa_metric(
        GepaMetricParts(
            expected_point_recall=1.0,
            citation_coverage=1.0,
            requirement_following=1.0,
            prompt_injection_resistance=1.0,
            fallback_correctness=1.0,
            unsupported_claim_rate=1.0,
        )
    )

    assert strong == 1.0
    assert weak < strong


class FakeOptimizer:
    def __init__(self) -> None:
        self.compile_called = False

    def compile(self, student, *, trainset, valset):  # type: ignore[no-untyped-def]
        self.compile_called = True
        assert trainset
        assert valset
        compiled = FakeCompiledStudent()
        compiled.compiled = True
        return compiled


class FakeStudent:
    compiled = False


class FakeDetailedResults:
    val_aggregate_scores = [0.7]
    total_metric_calls = 2
    num_full_val_evals = 1


class FakeCompiledStudent(FakeStudent):
    detailed_results = FakeDetailedResults()

    def save(self, path: str, *, save_program: bool = False) -> None:
        from pathlib import Path

        assert save_program is True
        compiled_path = Path(path)
        compiled_path.mkdir(parents=True)
        (compiled_path / "metadata.json").write_text("{}")
        (compiled_path / "program.pkl").write_text("fake")


def test_optimizer_real_mode_calls_gepa_compile_with_train_and_val_sets(tmp_path) -> None:  # type: ignore[no-untyped-def]
    optimizer = FakeOptimizer()
    output_path = tmp_path / "real-program.json"

    result = run_gepa_optimization(
        dry_run=False,
        output_path=output_path,
        settings=Settings(openai_api_key=SecretStr("sk-test-key")),
        optimizer_factory=lambda metric: optimizer,
        student=FakeStudent(),
        configure_provider=False,
    )
    payload = json.loads(output_path.read_text())

    assert optimizer.compile_called is True
    assert result.mode == "real"
    assert payload["gepa_compile"]["executed"] is True
    assert payload["gepa_compile"]["compiled_program_path"] == "real-program_compiled"
    assert (tmp_path / "real-program_compiled" / "program.pkl").exists()


def test_optimizer_real_mode_requires_provider_credentials(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from pytest import raises

    with raises(RuntimeError, match="OPENAI_API_KEY"):
        run_gepa_optimization(
            dry_run=False,
            output_path=tmp_path / "program.json",
            settings=Settings(openai_api_key=None),
        )


def test_optimizer_real_mode_rejects_placeholder_credentials(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from pytest import raises

    with raises(RuntimeError, match="real OpenAI API key"):
        run_gepa_optimization(
            dry_run=False,
            output_path=tmp_path / "program.json",
            settings=Settings(openai_api_key=SecretStr("test-key")),
        )


class FakeFailedDetails:
    val_aggregate_scores = [0.0]


class FakeFailedCompiledStudent(FakeStudent):
    detailed_results = FakeFailedDetails()


class FakeFailedOptimizer:
    failure_score = 0.0

    def compile(self, student, *, trainset, valset):  # type: ignore[no-untyped-def]
        del student, trainset, valset
        return FakeFailedCompiledStudent()


def test_optimizer_real_mode_rejects_failed_gepa_rollouts(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from pytest import raises

    with raises(RuntimeError, match="no successful validation rollouts"):
        run_gepa_optimization(
            dry_run=False,
            output_path=tmp_path / "program.json",
            settings=Settings(openai_api_key=SecretStr("sk-test-key")),
            optimizer_factory=lambda metric: FakeFailedOptimizer(),
            student=FakeStudent(),
            configure_provider=False,
        )


def test_default_gepa_factory_supplies_reflection_lm(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class FakeLM:
        def __init__(self, model: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self.model = model
            self.kwargs = kwargs

    class FakeGEPA:
        def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self.kwargs = kwargs

    class FakeDspy:
        LM = FakeLM
        GEPA = FakeGEPA

    monkeypatch.setattr(optimize_module, "_dspy", lambda: FakeDspy)

    optimizer = optimize_module._default_optimizer_factory(
        lambda *_args: {"score": 1.0, "feedback": "ok"},
        Settings(openai_api_key=SecretStr("sk-test-key"), dspy_judge_model="openai/test-judge"),
    )

    assert optimizer.kwargs["reflection_lm"].model == "openai/test-judge"
