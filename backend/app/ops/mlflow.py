"""MLflow tracking helpers with import-safe fallback behavior."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
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
    model_package: dict[str, Any] | None = None


@dataclass(frozen=True)
class MlflowSupportStatus:
    """Dev D-callable status for MLflow logging support."""

    callable: bool
    tracking_uri: str
    experiment_name: str = EXPERIMENT_NAME
    artifact_logging_supported: bool = False
    model_packaging_supported: bool = False
    skip_reason: str | None = None


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


def mlflow_support_status(settings: Settings) -> MlflowSupportStatus:
    """Return whether MLflow and DSPy packaging are importable without starting a run."""

    try:
        import_module("mlflow")
    except ImportError as exc:
        return MlflowSupportStatus(
            callable=False,
            tracking_uri=settings.mlflow_tracking_uri,
            skip_reason=f"mlflow_unavailable:{exc.name}",
        )
    except Exception as exc:
        return MlflowSupportStatus(
            callable=False,
            tracking_uri=settings.mlflow_tracking_uri,
            skip_reason=f"mlflow_import_failed:{exc.__class__.__name__}",
        )

    model_packaging_supported = True
    skip_reason = None
    try:
        mlflow_dspy = import_module("mlflow.dspy")
        if not callable(getattr(mlflow_dspy, "log_model", None)):
            model_packaging_supported = False
            skip_reason = "mlflow_dspy_log_model_missing"
    except ImportError as exc:
        model_packaging_supported = False
        skip_reason = f"mlflow_dspy_unavailable:{exc.name}"
    except Exception as exc:
        model_packaging_supported = False
        skip_reason = f"mlflow_dspy_import_failed:{exc.__class__.__name__}"

    return MlflowSupportStatus(
        callable=True,
        tracking_uri=settings.mlflow_tracking_uri,
        artifact_logging_supported=True,
        model_packaging_supported=model_packaging_supported,
        skip_reason=skip_reason,
    )


def build_quality_mlflow_payload(
    settings: Settings,
    *,
    provider: Mapping[str, Any] | None = None,
    metrics: Mapping[str, float] | None = None,
    artifacts: Sequence[Path] = (),
    model_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build params, metrics, artifacts, and metadata for Dev D MLflow calls."""

    safe_provider = dict(provider or {})
    params = {
        **build_default_mlflow_params(settings),
        "provider": str(safe_provider.get("selected_provider", "unknown")),
        "requested_provider": str(safe_provider.get("requested_provider", "unknown")),
        "provider_model": str(safe_provider.get("provider_model", "")),
        "provider_configured": bool(safe_provider.get("provider_configured", False)),
    }
    return {
        "status": mlflow_support_status(settings).__dict__,
        "params": params,
        "metrics": dict(metrics or {}),
        "artifacts": [str(path) for path in artifacts],
        "provider_metadata": safe_provider,
        "model_metadata": dict(model_metadata or {}),
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
    model_logger: Callable[[], Any] | None = None,
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
        model_package = model_logger() if model_logger else None
    return MlflowRunSummary(
        run_id=run_id,
        tracking_uri=settings.mlflow_tracking_uri,
        used_mlflow=True,
        artifacts=logged_artifacts,
        model_package=_package_payload(model_package),
    )


def _write_fallback_run(
    settings: Settings,
    params: Mapping[str, str | int | float | bool],
    metrics: dict[str, float],
    artifacts: list[Path],
    run_name: str,
    model_logger: Callable[[], Any] | None = None,
) -> MlflowRunSummary:
    del model_logger
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


def _package_payload(model_package: Any) -> dict[str, Any] | None:
    if model_package is None:
        return None
    if hasattr(model_package, "__dict__"):
        return dict(model_package.__dict__)
    if isinstance(model_package, dict):
        return model_package
    return {"value": str(model_package)}
