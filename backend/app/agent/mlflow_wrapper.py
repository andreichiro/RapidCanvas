"""MLflow packaging helpers for DSPy programs."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any

from app.agent.program import BlueskyExplainer


@dataclass(frozen=True)
class DspyModelPackageResult:
    """Result of attempting to package the DSPy program in MLflow."""

    packaged: bool
    artifact_path: str
    reason: str | None = None


def log_dspy_model(
    program: BlueskyExplainer,
    *,
    artifact_path: str = "dspy-program",
    task: str = "llm/v1/chat",
) -> DspyModelPackageResult:
    """Log the DSPy program through ``mlflow.dspy.log_model`` when available."""

    try:
        import_module("mlflow")
        mlflow_dspy = import_module("mlflow.dspy")
    except ImportError as exc:
        return DspyModelPackageResult(
            packaged=False,
            artifact_path=artifact_path,
            reason=f"mlflow_dspy_unavailable:{exc.name}",
        )

    log_model = getattr(mlflow_dspy, "log_model", None)
    if not callable(log_model):
        return DspyModelPackageResult(
            packaged=False,
            artifact_path=artifact_path,
            reason="mlflow_dspy_log_model_missing",
        )

    log_model(program, artifact_path=artifact_path, task=task)
    return DspyModelPackageResult(packaged=True, artifact_path=artifact_path)


def mlflow_model_signature() -> dict[str, Any]:
    """Return the public input/output sketch used in model package metadata."""

    return {
        "input": {
            "post_url": "https://bsky.app/profile/{actor}/post/{rkey}",
            "provider": "openai",
            "include_trace": True,
        },
        "output": {
            "bullets": [{"text": "source-backed bullet", "source_ids": ["S1"]}],
            "trace": {"fallback_mode": "none", "trust_score": 0.82},
        },
    }

