from __future__ import annotations

import json
import os

from pydantic import SecretStr

from app.agent.loader import configure_dspy, load_program
from app.config import Settings
from app.eval import optimize as optimize_module
from app.eval.optimize import GepaMetricParts, combined_gepa_metric, run_gepa_optimization
from app.ops import mlflow as mlflow_ops
from app.ops.mlflow import build_default_mlflow_params, dataset_hash, log_local_run


def test_optimizer_dry_run_saves_loadable_program(tmp_path) -> None:  # type: ignore[no-untyped-def]
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
    assert payload["gepa_compile"]["trainset_size"] == 1
    assert payload["gepa_compile"]["valset_size"] == 1


def test_optimizer_real_mode_requires_provider_credentials(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from pytest import raises

    with raises(RuntimeError, match="OPENAI_API_KEY"):
        run_gepa_optimization(dry_run=False, output_path=tmp_path / "program.json")


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
    total_metric_calls = 2
    num_full_val_evals = 1


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
    assert optimizer.kwargs["reflection_lm"].kwargs["temperature"] == 1.0


def test_configure_dspy_exports_settings_openai_key(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("OPENAI_API_KEY", "stale-key")

    warnings = configure_dspy(Settings(openai_api_key=SecretStr("sk-test-key")))

    assert warnings == []
    assert os.environ["OPENAI_API_KEY"] == "sk-test-key"


def test_mlflow_param_payload_includes_required_dev_c_fields() -> None:
    params = build_default_mlflow_params(Settings(openai_api_key=None))

    assert params["dspy_model"] == "openai/gpt-4.1-mini"
    assert params["guardrail_policy_version"] == "gate4-dev-c-v1"
    assert params["prompt_injection_detector_version"] == "heuristic-policy-v1"


def test_mlflow_fallback_run_writes_manifest_when_mlflow_missing(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    real_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):  # type: ignore[no-untyped-def]
        if name == "mlflow":
            raise ImportError("No module named mlflow")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)
    artifact = tmp_path / "artifact.json"
    artifact.write_text("{}")
    settings = Settings(openai_api_key=None, reports_dir=str(tmp_path))

    run = log_local_run(
        settings,
        params={"provider": "openai"},
        metrics={"citation_coverage": 1.0},
        artifacts=[artifact],
        run_name="test-run",
        model_logger=lambda: {"packaged": True},
    )

    assert run.used_mlflow is False
    assert run.artifacts[0].exists()
    assert "test-run" in run.artifacts[0].read_text()


def test_mlflow_model_logger_runs_inside_active_run(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class FakeRunInfo:
        run_id = "run-123"

    class FakeRun:
        info = FakeRunInfo()

        def __enter__(self):  # type: ignore[no-untyped-def]
            fake_mlflow.in_run = True
            return self

        def __exit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            fake_mlflow.in_run = False

    class FakeMlflow:
        def __init__(self) -> None:
            self.in_run = False
            self.logged_artifacts: list[str] = []

        def set_tracking_uri(self, uri: str) -> None:
            self.tracking_uri = uri

        def set_experiment(self, name: str) -> None:
            self.experiment = name

        def start_run(self, run_name: str) -> FakeRun:
            self.run_name = run_name
            return FakeRun()

        def log_params(self, params: dict[str, str]) -> None:
            self.params = params

        def log_metric(self, key: str, value: float) -> None:
            self.metric = (key, value)

        def log_artifact(self, artifact: str) -> None:
            self.logged_artifacts.append(artifact)

    fake_mlflow = FakeMlflow()
    artifact = tmp_path / "artifact.json"
    artifact.write_text("{}")
    monkeypatch.setattr(mlflow_ops, "import_module", lambda name: fake_mlflow)

    run = mlflow_ops.log_local_run(
        Settings(openai_api_key=None),
        params={"provider": "openai"},
        metrics={"citation_coverage": 1.0},
        artifacts=[artifact],
        run_name="test-run",
        model_logger=lambda: {"packaged": fake_mlflow.in_run},
    )

    assert run.used_mlflow is True
    assert run.model_package == {"packaged": True}
    assert fake_mlflow.logged_artifacts == [str(artifact)]


def test_dataset_hash_is_stable() -> None:
    payload = {"cases": ["a", "b"], "version": 1}

    assert dataset_hash(payload) == dataset_hash({"version": 1, "cases": ["a", "b"]})
