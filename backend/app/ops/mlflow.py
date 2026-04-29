"""MLflow tracking helpers with import-safe fallback behavior."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

from app.config import Settings

EXPERIMENT_NAME = "bluesky-post-explainer"


@dataclass(frozen=True)
class MlflowRunSummary:
    """Summary of a local MLflow or fallback tracking run."""

    run_id: str
    tracking_uri: str
    used_mlflow: bool
    artifacts: list[Path]


def build_default_mlflow_params(settings: Settings) -> dict[str, str | bool]:
    """Return the required Dev C parameter set for experiment tracking."""

    return {
        "dspy_model": settings.dspy_model,
        "dspy_judge_model": settings.dspy_judge_model,
        "embedding_model": settings.embedding_model,
        "vision_model": settings.vision_model,
        "vision_enabled": settings.enable_image_understanding,
        "hf_reranker_enabled": settings.enable_hf_reranker,
        "guardrail_policy_version": "gate4-dev-c-v1",
        "prompt_injection_detector_version": "heuristic-policy-v1",
    }


def dataset_hash(payload: Any) -> str:
    """Stable hash for eval datasets and parameter payloads."""

    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def log_local_run(
    settings: Settings,
    *,
    params: Mapping[str, str | int | float | bool],
    metrics: dict[str, float],
    artifacts: list[Path],
    run_name: str,
) -> MlflowRunSummary:
    """Create a local MLflow run, falling back to a manifest when MLflow is absent."""

    try:
        mlflow = import_module("mlflow")
    except ImportError:
        return _write_fallback_run(settings, params, metrics, artifacts, run_name)

    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    mlflow.set_experiment(EXPERIMENT_NAME)
    with mlflow.start_run(run_name=run_name) as active_run:
        run_id = active_run.info.run_id
        mlflow.log_params({key: str(value) for key, value in params.items()})
        for key, value in metrics.items():
            mlflow.log_metric(key, value)
        logged_artifacts: list[Path] = []
        for artifact in artifacts:
            if artifact.exists():
                mlflow.log_artifact(str(artifact))
                logged_artifacts.append(artifact)
    return MlflowRunSummary(
        run_id=run_id,
        tracking_uri=settings.mlflow_tracking_uri,
        used_mlflow=True,
        artifacts=logged_artifacts,
    )


def _write_fallback_run(
    settings: Settings,
    params: Mapping[str, str | int | float | bool],
    metrics: dict[str, float],
    artifacts: list[Path],
    run_name: str,
) -> MlflowRunSummary:
    reports_dir = Path(settings.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    run_id = dataset_hash({"params": params, "metrics": metrics, "run_name": run_name})[:12]
    fallback_path = reports_dir / f"mlflow_fallback_{run_id}.json"
    payload = {
        "run_id": run_id,
        "run_name": run_name,
        "tracking_uri": settings.mlflow_tracking_uri,
        "used_mlflow": False,
        "params": dict(params),
        "metrics": metrics,
        "artifacts": [str(artifact) for artifact in artifacts if artifact.exists()],
    }
    fallback_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return MlflowRunSummary(
        run_id=run_id,
        tracking_uri=settings.mlflow_tracking_uri,
        used_mlflow=False,
        artifacts=[fallback_path],
    )
