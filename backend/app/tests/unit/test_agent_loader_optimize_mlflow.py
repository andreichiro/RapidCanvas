from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

from pydantic import SecretStr

from app.agent.evidence_contract import normalize_retrieval_output
from app.agent.loader import ProgramLoadResult, configure_dspy, load_program
from app.agent.log_mlflow import _mlflow_artifacts, _write_manifest
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

    assert result.program.finalization_context().adapter_mode == "deterministic_fallback"
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
    assert result.program.finalization_context().adapter_mode == "none"


def test_load_program_rejects_compiled_path_outside_metadata_dir(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    class FakeDspy:
        @staticmethod
        def configure(**kwargs) -> None:  # type: ignore[no-untyped-def]
            del kwargs

        @staticmethod
        def load(path: str, *, allow_pickle: bool) -> object:
            raise AssertionError(f"unsafe compiled path should not load: {path} {allow_pickle}")

    outside_dir = tmp_path.parent / "outside-compiled"
    outside_dir.mkdir(exist_ok=True)
    optimized_path = tmp_path / "program.json"
    optimized_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gepa_compile": {"compiled_program_path": "../outside-compiled"},
            }
        )
    )
    monkeypatch.setattr("app.agent.loader.import_module", lambda name: FakeDspy)

    result = load_program(
        Settings(openai_api_key=SecretStr("sk-test-key")),
        optimized_path=optimized_path,
        prefer_dspy=True,
    )

    assert "optimized_dspy_program_path_outside_metadata_dir" in result.warnings


def test_load_program_can_package_live_dspy_without_key() -> None:
    result = load_program(
        Settings(openai_api_key=None),
        prefer_dspy=True,
        allow_dspy_without_key=True,
    )

    assert result.program.finalization_context().adapter_mode == "none"


def test_mlflow_param_payload_includes_required_dev_c_fields() -> None:
    params = build_default_mlflow_params(Settings(openai_api_key=None))

    assert params["provider"] == "openai"
    assert params["dspy_model"] == "openai/gpt-4.1-mini"
    assert params["guardrail_policy_version"] == "runtime-guardrails-v1"
    assert params["prompt_injection_detector_version"] == "heuristic-policy-v1"
    assert params["source_quality_policy_version"] == "source_quality_v1"
    assert params["retrieval_backend"] == "qdrant_vector_store_local_path"
    assert params["chunking_name"] == "medium_700_100"
    assert params["retrieval_timeout_seconds"] == 25.0


def test_mlflow_manifest_records_real_gepa_optimization_status(tmp_path) -> None:  # type: ignore[no-untyped-def]
    class FakeProgram:
        optimized_config = {
            "optimizer": "GEPA",
            "mode": "real",
            "metric_score": 0.875,
            "gepa_compile": {
                "executed": True,
                "compiled_program_path": "program_compiled",
            },
            "dataset_bridge": {
                "source": "eval/posts.yaml plus cached fixtures",
                "case_count": 19,
                "trainset_size": 10,
                "devset_size": 4,
                "holdout_size": 5,
                "source_quality_policy_version": "source_quality_v1",
                "average_expected_source_quality_score": 0.75,
                "average_expected_citation_relevance_score": 1.0,
            },
            "artifact_status": {
                "kind": "real_compiled_dspy_artifact",
                "compiled_artifact_present": True,
            },
        }
        provider_metadata = {
            "requested_provider": "openai",
            "selected_provider": "openai",
            "provider_model": "openai/gpt-4.1-mini",
            "provider_configured": True,
        }

    manifest_path = _write_manifest(
        Settings(openai_api_key=None, reports_dir=str(tmp_path)),
        ProgramLoadResult(
            program=cast(Any, FakeProgram()),
            optimized_path=Path("backend/app/agent/optimized/program.json"),
            warnings=["optimized_dspy_program_loaded"],
        ),
    )
    payload = json.loads(manifest_path.read_text())
    status = payload["optimization_status"]

    assert status["optimizer"] == "GEPA"
    assert status["mode"] == "real"
    assert status["compile_executed"] is True
    assert status["compiled_program_path"] == "program_compiled"
    assert status["artifact_kind"] == "real_compiled_dspy_artifact"
    assert status["source_quality_policy_version"] == "source_quality_v1"
    assert status["dataset_case_count"] == 19
    assert status["trainset_size"] == 10
    assert payload["provider"]["selected_provider"] == "openai"
    assert payload["source_quality_policy_version"] == "source_quality_v1"
    assert payload["retrieval_backend"] == "qdrant_vector_store_local_path"
    assert payload["requirements_matrix_snapshot"]["row_count"] > 0
    assert "optimized_dspy_program_loaded" in payload["loader_warnings"]


def test_mlflow_artifact_bundle_includes_eval_provider_live_matrix_and_optimized_paths(
    tmp_path: Path,
) -> None:
    class FakeProgram:
        optimized_config: dict[str, Any] = {}
        provider_metadata: dict[str, Any] = {}

    reports_dir = tmp_path / "reports"
    (reports_dir / "eval").mkdir(parents=True)
    (reports_dir / "eval" / "summary.json").write_text("{}")
    (reports_dir / "provider_comparison.json").write_text("{}")
    manifest = reports_dir / "mlflow_runtime_manifest.json"
    manifest.write_text("{}")
    optimized_path = tmp_path / "program.json"
    optimized_path.write_text("{}")
    compiled = tmp_path / "program_compiled"
    compiled.mkdir()
    (compiled / "metadata.json").write_text("{}")
    (compiled / "program.pkl").write_text("fake")

    artifacts = _mlflow_artifacts(
        Settings(openai_api_key=None, reports_dir=str(reports_dir)),
        manifest,
        ProgramLoadResult(
            program=cast(Any, FakeProgram()),
            optimized_path=optimized_path,
            warnings=[],
        ),
    )

    artifact_names = {path.name for path in artifacts}
    assert {"summary.json", "provider_comparison.json", "program.json", "program.pkl"} <= (
        artifact_names
    )
    assert any(path.name == "requirements_matrix.md" for path in artifacts)


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
        params={"provider": "openai", "api_key": "sk-live-secret-12345"},
        metrics={"citation_coverage": 1.0},
        artifacts=[artifact],
        run_name="test-run",
        model_logger=lambda: {"packaged": fake_mlflow.in_run},
    )

    assert run.used_mlflow is True
    assert run.model_package == {"packaged": True}
    assert fake_mlflow.logged_artifacts == [str(artifact)]
    assert "api_key" not in fake_mlflow.params
    assert fake_mlflow.params["redacted_sensitive_fields"] == "1"


def test_dataset_hash_is_stable() -> None:
    payload = {"cases": ["a", "b"], "version": 1}

    assert dataset_hash(payload) == dataset_hash({"version": 1, "cases": ["a", "b"]})
