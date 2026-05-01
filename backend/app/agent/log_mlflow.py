"""CLI entry point for logging a local Dev C MLflow smoke run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.agent.loader import ProgramLoadResult, load_program
from app.agent.mlflow_wrapper import (
    log_dspy_model,
    mlflow_model_signature,
)
from app.config import Settings, get_settings
from app.ops.mlflow import MlflowRunSummary, build_default_mlflow_params, log_local_run


def main(argv: list[str] | None = None) -> int:
    """Create a local MLflow run with Dev C parameters and artifacts."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracking-uri", default=None)
    parser.add_argument("--reports-dir", default=None)
    parser.add_argument("--skip-model-package", action="store_true")
    args = parser.parse_args(argv)

    settings = _settings_from_args(args.tracking_uri, args.reports_dir)
    program_result = load_program(settings, prefer_dspy=True, allow_dspy_without_key=True)
    manifest_path = _write_manifest(settings, program_result)
    run = log_local_run(
        settings,
        params=build_default_mlflow_params(settings),
        metrics={
            "expected_point_recall": 0.0,
            "citation_coverage": 1.0,
            "prompt_injection_resistance": 1.0,
            "unsupported_claim_rate": 0.0,
        },
        artifacts=[manifest_path],
        run_name="gate4-dev-c-smoke",
        model_logger=None
        if args.skip_model_package
        else lambda: log_dspy_model(program_result.program),
    )

    print(json.dumps(_summary_payload(run), indent=2, sort_keys=True))
    return 0


def _settings_from_args(tracking_uri: str | None, reports_dir: str | None) -> Settings:
    settings = get_settings()
    updates: dict[str, str] = {}
    if tracking_uri:
        updates["mlflow_tracking_uri"] = tracking_uri
    if reports_dir:
        updates["reports_dir"] = reports_dir
    return settings.model_copy(update=updates) if updates else settings


def _write_manifest(settings: Settings, program_result: ProgramLoadResult) -> Path:
    reports_dir = Path(settings.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = reports_dir / "mlflow_gate4_manifest.json"
    manifest = {
        "lane": "dev_c",
        "policy_version": "gate4-dev-c-v1",
        "optimized_path": (
            str(program_result.optimized_path) if program_result.optimized_path else None
        ),
        "loader_warnings": program_result.warnings,
        "model_signature": mlflow_model_signature(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest_path


def _summary_payload(run: MlflowRunSummary) -> dict[str, object]:
    return {
        "run_id": run.run_id,
        "tracking_uri": run.tracking_uri,
        "used_mlflow": run.used_mlflow,
        "artifacts": [str(path) for path in run.artifacts],
        "package": run.model_package,
        "skip_reason": run.skip_reason,
    }


if __name__ == "__main__":
    raise SystemExit(main())
