from __future__ import annotations

import json
import os
from typing import Any, cast

from pydantic import SecretStr

from app.agent.loader import configure_dspy, load_program
from app.config import Settings
from app.ops import mlflow as mlflow_ops
from app.ops.mlflow import build_default_mlflow_params, dataset_hash, log_local_run


def test_configure_dspy_exports_settings_openai_key(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("OPENAI_API_KEY", "stale-key")

    warnings = configure_dspy(Settings(openai_api_key=SecretStr("sk-test-key")))

    assert warnings == []
    assert os.environ["OPENAI_API_KEY"] == "sk-test-key"


def test_load_program_loads_compiled_dspy_program(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    class FakeLM:
        def __init__(self, model: str) -> None:
            self.model = model

    class FakeDspy:
        LM = FakeLM
        loaded_path: str | None = None
        loaded_program = object()

        @staticmethod
        def configure(**kwargs) -> None:  # type: ignore[no-untyped-def]
            del kwargs

        @staticmethod
        def load(path: str, *, allow_pickle: bool) -> object:
            FakeDspy.loaded_path = path
            assert allow_pickle is True
            return FakeDspy.loaded_program

    optimized_dir = tmp_path / "compiled"
    optimized_dir.mkdir()
    optimized_path = tmp_path / "program.json"
    optimized_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gepa_compile": {"compiled_program_path": optimized_dir.name},
            }
        )
    )
    monkeypatch.setattr("app.agent.loader.import_module", lambda name: FakeDspy)

    result = load_program(
        Settings(openai_api_key=SecretStr("sk-test-key")),
        optimized_path=optimized_path,
        prefer_dspy=True,
    )

    assert FakeDspy.loaded_path == str(optimized_dir)
    assert "optimized_dspy_program_loaded" in result.warnings
    assert result.program._runner.adapter_mode == "none"  # type: ignore[attr-defined]
    runner = cast(Any, result.program._runner)
    assert runner._optimized_explain_program is FakeDspy.loaded_program


def test_load_program_can_package_live_dspy_without_key() -> None:
    result = load_program(
        Settings(openai_api_key=None),
        prefer_dspy=True,
        allow_dspy_without_key=True,
    )

    assert result.program._runner.adapter_mode == "none"  # type: ignore[attr-defined]


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
