from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.config import Settings
from app.ops import mlflow as mlflow_ops
from app.ops.mlflow import build_quality_mlflow_payload, mlflow_support_status


def test_mlflow_support_status_reports_import_skip(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fake_import_module(name: str) -> object:
        raise ImportError(name=name)

    monkeypatch.setattr(mlflow_ops, "import_module", fake_import_module)

    status = mlflow_support_status(Settings(openai_api_key=None))

    assert status.callable is False
    assert status.skip_reason == "mlflow_unavailable:mlflow"


def test_mlflow_support_status_reports_model_packaging_skip(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fake_import_module(name: str) -> object:
        if name == "mlflow":
            return SimpleNamespace()
        raise ImportError(name=name)

    monkeypatch.setattr(mlflow_ops, "import_module", fake_import_module)

    status = mlflow_support_status(Settings(openai_api_key=None))

    assert status.callable is True
    assert status.artifact_logging_supported is True
    assert status.model_packaging_supported is False
    assert status.skip_reason == "mlflow_dspy_unavailable:mlflow.dspy"


def test_quality_mlflow_payload_is_structured_and_secret_free() -> None:
    payload = build_quality_mlflow_payload(
        Settings(openai_api_key=None),
        provider={
            "requested_provider": "gemini",
            "selected_provider": "openai",
            "provider_model": "openai/gpt-4.1-mini",
            "provider_configured": True,
        },
        metrics={"citation_coverage": 1.0},
        artifacts=[Path("reports/eval/summary.json")],
        model_metadata={"program": "baseline"},
    )

    assert payload["params"]["provider"] == "openai"
    assert payload["params"]["requested_provider"] == "gemini"
    assert payload["metrics"] == {"citation_coverage": 1.0}
    assert payload["artifacts"] == ["reports/eval/summary.json"]
    assert "api_key" not in str(payload).lower()
