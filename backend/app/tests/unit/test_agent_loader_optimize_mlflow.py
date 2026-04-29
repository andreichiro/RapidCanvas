from __future__ import annotations

import json

from app.agent.loader import load_program
from app.config import Settings
from app.eval.optimize import GepaMetricParts, combined_gepa_metric, run_gepa_optimization
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
    )

    assert run.used_mlflow is False
    assert run.artifacts[0].exists()
    assert "test-run" in run.artifacts[0].read_text()


def test_dataset_hash_is_stable() -> None:
    payload = {"cases": ["a", "b"], "version": 1}

    assert dataset_hash(payload) == dataset_hash({"version": 1, "cases": ["a", "b"]})
