"""MLflow tracking helpers with import-safe fallback behavior."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

from app.config import Settings
from app.guardrails.policies import DEFAULT_POLICY

EXPERIMENT_NAME = "bluesky-post-explainer"
SENSITIVE_KEY_MARKERS = ("api_key", "apikey", "token", "secret", "password", "credential")
SECRET_VALUE_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
SOURCE_QUALITY_POLICY_VERSION = "source_quality_v1"
DEFAULT_CHUNKING_NAME = "medium_700_100"
DEFAULT_CHUNK_SIZE = 700
DEFAULT_CHUNK_OVERLAP = 100
DEFAULT_RETRIEVAL_CONCURRENCY = 1
DEFAULT_RETRIEVAL_TIMEOUT_SECONDS = 8.0


@dataclass(frozen=True)
class MlflowRunSummary:
    """Summary of a local MLflow or fallback tracking run."""

    run_id: str
    tracking_uri: str
    used_mlflow: bool
    artifacts: list[Path]
    model_package: dict[str, Any] | None = None
    skip_reason: str | None = None


@dataclass(frozen=True)
class MlflowSupportStatus:
    """Callable status for MLflow logging support."""

    callable: bool
    tracking_uri: str
    experiment_name: str = EXPERIMENT_NAME
    artifact_logging_supported: bool = False
    model_packaging_supported: bool = False
    skip_reason: str | None = None


def build_default_mlflow_params(settings: Settings) -> dict[str, str | int | float | bool]:
    """Return the required runtime parameter set for experiment tracking."""

    return {
        "provider": "openai",
        "dspy_model": settings.dspy_model,
        "dspy_judge_model": settings.dspy_judge_model,
        "embedding_model": settings.embedding_model,
        "vision_model": settings.vision_model,
        "vision_enabled": settings.enable_image_understanding,
        "hf_reranker_enabled": settings.enable_hf_reranker,
        "guardrail_policy_version": DEFAULT_POLICY.version,
        "prompt_injection_detector_version": "heuristic-policy-v1",
        "source_quality_policy_version": SOURCE_QUALITY_POLICY_VERSION,
        "retrieval_backend": _configured_retrieval_backend(settings),
        "qdrant_url_configured": settings.qdrant_url is not None,
        "qdrant_path_configured": bool(settings.qdrant_path),
        "chunking_name": DEFAULT_CHUNKING_NAME,
        "chunk_size": DEFAULT_CHUNK_SIZE,
        "chunk_overlap": DEFAULT_CHUNK_OVERLAP,
        "retrieval_max_queries": settings.retrieval_max_queries,
        "retrieval_search_limit_per_provider": settings.retrieval_search_limit_per_provider,
        "retrieval_linked_page_limit": settings.retrieval_linked_page_limit,
        "retrieval_linked_page_concurrency": _setting(
            settings,
            "retrieval_linked_page_concurrency",
            DEFAULT_RETRIEVAL_CONCURRENCY,
        ),
        "retrieval_search_concurrency": _setting(
            settings,
            "retrieval_search_concurrency",
            DEFAULT_RETRIEVAL_CONCURRENCY,
        ),
        "retrieval_timeout_seconds": _setting(
            settings,
            "retrieval_timeout_seconds",
            DEFAULT_RETRIEVAL_TIMEOUT_SECONDS,
        ),
    }


def _setting(settings: Settings, name: str, default: int | float) -> int | float:
    value = getattr(settings, name, default)
    return value if isinstance(value, (int, float)) else default


def _configured_retrieval_backend(settings: Settings) -> str:
    if settings.qdrant_url:
        return "qdrant_vector_store"
    if settings.qdrant_path:
        return "qdrant_vector_store_local_path"
    return "in_memory_fallback"


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
    """Build params, metrics, artifacts, and metadata for MLflow calls."""

    safe_provider = _redact_mapping(provider or {})
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
        "model_metadata": _redact_mapping(model_metadata or {}),
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

    mlflow, import_skip_reason = _import_mlflow_for_run()
    if import_skip_reason:
        return _write_fallback_run(
            settings,
            params,
            metrics,
            artifacts,
            run_name,
            skip_reason=import_skip_reason,
        )

    try:
        safe_params = _redact_mapping(params)
        run_id, logged_artifacts, model_package = _run_mlflow_tracking(
            mlflow,
            settings,
            params=safe_params,
            metrics=metrics,
            artifacts=artifacts,
            run_name=run_name,
            model_logger=model_logger,
        )
    except Exception as exc:
        return _write_fallback_run(
            settings,
            _redact_mapping(params),
            metrics,
            artifacts,
            run_name,
            skip_reason=f"mlflow_run_failed:{exc.__class__.__name__}",
        )
    return MlflowRunSummary(
        run_id=run_id,
        tracking_uri=settings.mlflow_tracking_uri,
        used_mlflow=True,
        artifacts=logged_artifacts,
        model_package=_package_payload(model_package),
    )


def _import_mlflow_for_run() -> tuple[Any | None, str | None]:
    try:
        return import_module("mlflow"), None
    except ImportError as exc:
        return None, f"mlflow_unavailable:{exc.name}"
    except Exception as exc:
        return None, f"mlflow_import_failed:{exc.__class__.__name__}"


def _run_mlflow_tracking(
    mlflow: Any,
    settings: Settings,
    *,
    params: Mapping[str, str | int | float | bool],
    metrics: dict[str, float],
    artifacts: list[Path],
    run_name: str,
    model_logger: Callable[[], Any] | None,
) -> tuple[str, list[Path], Any]:
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    mlflow.set_experiment(EXPERIMENT_NAME)
    with mlflow.start_run(run_name=run_name) as active_run:
        run_id = active_run.info.run_id
        mlflow.log_params({key: str(value) for key, value in params.items()})
        for key, value in metrics.items():
            mlflow.log_metric(key, value)
        logged_artifacts = _log_existing_artifacts(mlflow, artifacts)
        model_package = model_logger() if model_logger else None
    return run_id, logged_artifacts, model_package


def _log_existing_artifacts(mlflow: Any, artifacts: list[Path]) -> list[Path]:
    logged_artifacts: list[Path] = []
    for artifact in artifacts:
        if artifact.exists():
            mlflow.log_artifact(str(artifact))
            logged_artifacts.append(artifact)
    return logged_artifacts


def _write_fallback_run(
    settings: Settings,
    params: Mapping[str, str | int | float | bool],
    metrics: dict[str, float],
    artifacts: list[Path],
    run_name: str,
    model_logger: Callable[[], Any] | None = None,
    skip_reason: str | None = None,
) -> MlflowRunSummary:
    del model_logger
    reports_dir = Path(settings.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    safe_params = _redact_mapping(params)
    run_id = dataset_hash({"params": safe_params, "metrics": metrics, "run_name": run_name})[:12]
    fallback_path = reports_dir / f"mlflow_fallback_{run_id}.json"
    payload = {
        "run_id": run_id,
        "run_name": run_name,
        "tracking_uri": settings.mlflow_tracking_uri,
        "used_mlflow": False,
        "params": safe_params,
        "metrics": metrics,
        "artifacts": [str(artifact) for artifact in artifacts if artifact.exists()],
        "skip_reason": skip_reason,
    }
    fallback_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return MlflowRunSummary(
        run_id=run_id,
        tracking_uri=settings.mlflow_tracking_uri,
        used_mlflow=False,
        artifacts=[fallback_path],
        skip_reason=skip_reason,
    )


def _package_payload(model_package: Any) -> dict[str, Any] | None:
    if model_package is None:
        return None
    if hasattr(model_package, "__dict__"):
        return _redact_mapping(model_package.__dict__)
    if isinstance(model_package, dict):
        return _redact_mapping(model_package)
    return {"value": SECRET_VALUE_RE.sub("[redacted]", str(model_package))}


def _redact_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    redacted_count = 0
    for raw_key, value in mapping.items():
        key = str(raw_key)
        if _is_sensitive_key(key):
            redacted_count += 1
            continue
        safe[key] = _redact_value(value)
    if redacted_count:
        safe["redacted_sensitive_fields"] = redacted_count
    return safe


def _redact_value(value: Any) -> Any:
    if callable(getattr(value, "get_secret_value", None)):
        return "[redacted]"
    if isinstance(value, Mapping):
        return _redact_mapping(value)
    if isinstance(value, str):
        return SECRET_VALUE_RE.sub("[redacted]", value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_redact_value(item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(marker in normalized for marker in SENSITIVE_KEY_MARKERS)
