from __future__ import annotations

import json
import os
from typing import Any, cast

from pydantic import SecretStr

from app.agent.evidence_contract import normalize_retrieval_output
from app.agent.loader import configure_dspy, load_program
from app.agent.providers import resolve_provider
from app.config import Settings
from app.ops import mlflow as mlflow_ops
from app.ops.mlflow import build_default_mlflow_params, dataset_hash, log_local_run
from app.schemas.domain import ContextDocument, Evidence


def test_configure_dspy_exports_settings_openai_key(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("OPENAI_API_KEY", "stale-key")

    warnings = configure_dspy(Settings(openai_api_key=SecretStr("sk-test-key")))

    assert warnings == []
    assert os.environ["OPENAI_API_KEY"] == "sk-test-key"


def test_optional_provider_missing_is_skipped_to_openai_default() -> None:
    resolution = resolve_provider(
        Settings(openai_api_key=SecretStr("sk-test-key"), gemini_api_key=None),
        "gemini",
    )

    assert resolution.selected.name == "openai"
    assert "provider_gemini_skipped:GEMINI_API_KEY is not configured" in resolution.warnings
    assert "provider_openai_default_used" in resolution.warnings


def test_unconfigured_provider_loads_deterministic_runner_with_skip_warning() -> None:
    result = load_program(
        Settings(openai_api_key=None, anthropic_api_key=None),
        prefer_dspy=True,
        provider_name="anthropic",
    )

    assert result.program._runner.adapter_mode == "deterministic_dev"  # type: ignore[attr-defined]
    assert any("provider_anthropic_skipped" in warning for warning in result.warnings)


def test_normalize_retrieval_output_consumes_diagnostics_and_source_safety() -> None:
    document = ContextDocument(
        id="D1",
        source_type="web",
        title="Source",
        url="https://example.com/source",
        text="Source text",
    )
    evidence = Evidence(
        id="E1",
        document_id="D1",
        text="Evidence text",
        score=0.8,
        source_id="S1",
    )
    output = {
        "context_documents": [document],
        "evidence": [evidence],
        "diagnostics": {
            "warnings": ["retrieval_warning"],
            "prompt_injection_flags": ["prompt_injection_risk"],
            "source_safety_diagnostics": ["private_url_blocked"],
            "private_url_blocks": ["blocked_link:http://127.0.0.1/admin"],
        },
        "warnings": ["result_warning"],
    }

    bundle = normalize_retrieval_output(output)

    assert bundle.evidence == (evidence,)
    assert bundle.documents == (document,)
    assert bundle.warnings == ("result_warning", "retrieval_warning")
    assert bundle.guardrail_flags == (
        "prompt_injection_risk",
        "source_safety_private_url_blocked",
    )
    assert bundle.source_safety_diagnostics == (
        "private_url_blocked",
        "blocked_link:http://127.0.0.1/admin",
    )


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
    def fake_import_module(name: str) -> object:
        if name == "mlflow":
            raise ImportError(name=name)
        return object()

    monkeypatch.setattr(mlflow_ops, "import_module", fake_import_module)
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
    assert run.skip_reason == "mlflow_unavailable:mlflow"
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
