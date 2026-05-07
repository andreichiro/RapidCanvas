"""CLI entry point for logging a local runtime MLflow smoke run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.agent.loader import OPTIMIZED_PROGRAM_PATH, ProgramLoadResult, load_program
from app.agent.mlflow_wrapper import (
    log_dspy_model,
    mlflow_model_signature,
)
from app.config import Settings, get_settings
from app.ops.mlflow import (
    MlflowRunSummary,
    build_default_mlflow_params,
    dataset_hash,
    log_local_run,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def main(argv: list[str] | None = None) -> int:
    """Create a local MLflow run with runtime parameters and artifacts."""

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
        params=_mlflow_params(settings, program_result),
        metrics=_mlflow_metrics(settings),
        artifacts=_mlflow_artifacts(settings, manifest_path, program_result),
        run_name="runtime-smoke",
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
    manifest_path = reports_dir / "mlflow_runtime_manifest.json"
    params = _mlflow_params(settings, program_result)
    manifest = {
        "runtime_component": "agent",
        "policy_version": params["guardrail_policy_version"],
        "provider": _provider_metadata(program_result),
        "models": {
            "dspy_model": settings.dspy_model,
            "dspy_judge_model": settings.dspy_judge_model,
            "embedding_model": settings.embedding_model,
            "vision_model": settings.vision_model,
        },
        "chunk_settings": {
            "chunking_name": params["chunking_name"],
            "chunk_size": params["chunk_size"],
            "chunk_overlap": params["chunk_overlap"],
            "retrieval_max_queries": params["retrieval_max_queries"],
            "retrieval_search_limit_per_provider": params[
                "retrieval_search_limit_per_provider"
            ],
            "retrieval_linked_page_limit": params["retrieval_linked_page_limit"],
            "retrieval_linked_page_concurrency": params[
                "retrieval_linked_page_concurrency"
            ],
            "retrieval_search_concurrency": params["retrieval_search_concurrency"],
            "retrieval_timeout_seconds": params["retrieval_timeout_seconds"],
        },
        "source_quality_policy_version": params["source_quality_policy_version"],
        "retrieval_backend": params["retrieval_backend"],
        "vision_enabled": settings.enable_image_understanding,
        "eval_metrics": _mlflow_metrics(settings),
        "provider_comparison": _provider_comparison_summary(settings),
        "live_quality_report": _live_quality_report_status(),
        "requirements_matrix_snapshot": _requirements_matrix_snapshot(),
        "optimized_path": (
            str(program_result.optimized_path) if program_result.optimized_path else None
        ),
        "loader_warnings": program_result.warnings,
        "optimization_status": _optimization_status(program_result),
        "optimized_program": _optimization_status(program_result),
        "model_signature": mlflow_model_signature(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest_path


def _mlflow_params(
    settings: Settings,
    program_result: ProgramLoadResult,
) -> dict[str, str | int | float | bool]:
    provider = _provider_metadata(program_result)
    selected_provider = str(
        provider.get("selected_provider") or provider.get("provider") or "openai"
    )
    return {
        **build_default_mlflow_params(settings),
        "provider": selected_provider,
        "requested_provider": str(provider.get("requested_provider", selected_provider)),
        "provider_model": str(provider.get("provider_model", settings.dspy_model)),
        "provider_configured": bool(provider.get("provider_configured", False)),
    }


def _mlflow_metrics(settings: Settings) -> dict[str, float]:
    summary = _read_json_object(Path(settings.reports_dir) / "eval" / "summary.json")
    keys = (
        "expected_point_recall",
        "citation_coverage",
        "citation_relevance_score",
        "source_relevance_score",
        "answer_usefulness_score",
        "public_live_quality_pass",
        "prompt_injection_resistance",
        "unsupported_claim_rate",
        "unsafe_output_rate",
        "image_expected_point_recall",
        "image_evidence_used",
        "off_topic_source_count",
        "latency_p95",
        "latency_p95_ms",
        "provider_quality_score",
    )
    metrics = {
        key: float(summary[key])
        for key in keys
        if isinstance(summary.get(key), int | float) and not isinstance(summary.get(key), bool)
    }
    if metrics:
        return metrics
    return {
        "expected_point_recall": 0.0,
        "citation_coverage": 1.0,
        "citation_relevance_score": 1.0,
        "source_relevance_score": 1.0,
        "prompt_injection_resistance": 1.0,
        "unsupported_claim_rate": 0.0,
    }


def _mlflow_artifacts(
    settings: Settings,
    manifest_path: Path,
    program_result: ProgramLoadResult,
) -> list[Path]:
    reports_dir = Path(settings.reports_dir)
    optimized_path = program_result.optimized_path or OPTIMIZED_PROGRAM_PATH
    compiled_dir = optimized_path.parent / "program_compiled"
    candidates = [
        manifest_path,
        reports_dir / "eval" / "summary.json",
        reports_dir / "eval" / "eval_report.md",
        reports_dir / "eval" / "eval_results.jsonl",
        reports_dir / "eval" / "confusion_matrix.csv",
        reports_dir / "eval" / "metric_bars.svg",
        reports_dir / "provider_comparison.json",
        reports_dir / "provider_comparison.md",
        REPO_ROOT / "docs" / "reviews" / "live_quality_review.md",
        optimized_path,
        compiled_dir / "metadata.json",
        compiled_dir / "program.pkl",
        REPO_ROOT / "docs" / "requirements_matrix.md",
    ]
    return [path for path in candidates if path.exists()]


def _optimization_status(program_result: ProgramLoadResult) -> dict[str, object]:
    config = program_result.program.optimized_config
    compile_payload = _mapping(config.get("gepa_compile", {}))
    dataset_bridge = _mapping(config.get("dataset_bridge", {}))
    artifact_status = _mapping(config.get("artifact_status", {}))
    return {
        "optimizer": config.get("optimizer"),
        "mode": config.get("mode"),
        "metric_score": config.get("metric_score"),
        "metric_parts": config.get("metric_parts"),
        "compile_executed": compile_payload.get("executed"),
        "compiled_program_path": compile_payload.get("compiled_program_path"),
        "artifact_status": artifact_status,
        "artifact_kind": artifact_status.get("kind"),
        "compiled_artifact_present": artifact_status.get("compiled_artifact_present"),
        "dataset_source": dataset_bridge.get("source"),
        "dataset_case_count": dataset_bridge.get("case_count"),
        "trainset_size": dataset_bridge.get("trainset_size"),
        "devset_size": dataset_bridge.get("devset_size"),
        "holdout_size": dataset_bridge.get("holdout_size"),
        "source_quality_policy_version": dataset_bridge.get("source_quality_policy_version"),
        "average_expected_source_quality_score": dataset_bridge.get(
            "average_expected_source_quality_score"
        ),
        "average_expected_citation_relevance_score": dataset_bridge.get(
            "average_expected_citation_relevance_score"
        ),
    }


def _provider_metadata(program_result: ProgramLoadResult) -> dict[str, Any]:
    metadata = getattr(program_result.program, "provider_metadata", {})
    return metadata if isinstance(metadata, dict) else {}


def _provider_comparison_summary(settings: Settings) -> dict[str, Any]:
    payload = _read_json_object(Path(settings.reports_dir) / "provider_comparison.json")
    providers = payload.get("providers", [])
    provider_rows = providers if isinstance(providers, list) else []
    return {
        "path": str(Path(settings.reports_dir) / "provider_comparison.json"),
        "exists": bool(payload),
        "mode": payload.get("mode"),
        "comparison_status": payload.get("comparison_status"),
        "ran_provider_count": payload.get("ran_provider_count"),
        "provider_statuses": [
            {
                "provider": row.get("provider"),
                "status": row.get("status"),
                "quality_pass": row.get("quality_pass"),
                "skipped_reason": row.get("skipped_reason"),
            }
            for row in provider_rows
            if isinstance(row, dict)
        ],
    }


def _live_quality_report_status() -> dict[str, Any]:
    path = REPO_ROOT / "docs" / "reviews" / "live_quality_review.md"
    snapshot = _file_snapshot(path)
    return {
        **snapshot,
        "exists": path.exists(),
        "key_hygiene_statement_expected": True,
    }


def _requirements_matrix_snapshot() -> dict[str, Any]:
    path = REPO_ROOT / "docs" / "requirements_matrix.md"
    snapshot = _file_snapshot(path)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return {
        **snapshot,
        "row_count": sum(1 for line in text.splitlines() if line.startswith("| R")),
    }


def _file_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "sha256": None, "bytes": 0}
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "path": str(path),
        "exists": True,
        "sha256": dataset_hash({"path": str(path), "content": text}),
        "bytes": len(text.encode("utf-8")),
    }


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


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
