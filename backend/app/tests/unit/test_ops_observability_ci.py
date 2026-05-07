from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from _pytest.logging import LogCaptureFixture
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api.request_context import (
    REQUEST_ID_HEADER,
    RequestContextMiddleware,
    configure_request_logging,
    current_request_id,
)

ROOT = Path(__file__).resolve().parents[4]


def test_request_context_preserves_safe_request_id_and_sets_response_header() -> None:
    app = _request_context_app()
    client = TestClient(app)

    response = client.get("/probe", headers={REQUEST_ID_HEADER: "review-request-1"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "review-request-1"
    assert response.json() == {
        "context_request_id": "review-request-1",
        "state_request_id": "review-request-1",
    }


def test_request_context_replaces_unsafe_request_id_and_logs_sanitized_path(
    caplog: LogCaptureFixture,
) -> None:
    app = _request_context_app()
    client = TestClient(app)
    caplog.set_level(logging.INFO, logger="app.api.request")

    response = client.get(
        "/probe?api_key=should-not-appear",
        headers={REQUEST_ID_HEADER: "bad\nrequest-id"},
    )

    assert response.status_code == 200
    request_id = response.headers["x-request-id"]
    assert request_id != "bad\nrequest-id"
    assert re.fullmatch(r"[a-f0-9]{32}", request_id)

    log_payload = json.loads(caplog.records[-1].message)
    assert log_payload["event"] == "http_request"
    assert log_payload["request_id"] == request_id
    assert log_payload["path"] == "/probe"
    assert "api_key" not in caplog.records[-1].message


def test_request_logging_configuration_is_idempotent_and_info_visible() -> None:
    request_logger = logging.getLogger("app.api.request")

    configure_request_logging()
    marked_handlers = [
        handler
        for handler in request_logger.handlers
        if getattr(handler, "_rapidcanvas_request_log_handler", False)
    ]
    configure_request_logging()
    marked_handlers_after_second_call = [
        handler
        for handler in request_logger.handlers
        if getattr(handler, "_rapidcanvas_request_log_handler", False)
    ]

    assert request_logger.level == logging.INFO
    assert len(marked_handlers) == 1
    assert marked_handlers_after_second_call == marked_handlers


def test_docker_compose_has_healthchecks_and_health_based_dependencies() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    for service in ("qdrant", "mlflow", "backend", "frontend"):
        assert _service_block(compose, service).count("healthcheck:") == 1

    qdrant = _service_block(compose, "qdrant")
    assert "/dev/tcp/127.0.0.1/6333" in qdrant
    assert "timeout 5 bash" in qdrant

    mlflow = _service_block(compose, "mlflow")
    assert "http://127.0.0.1:5000/" in mlflow

    backend = _service_block(compose, "backend")
    assert "qdrant:" in backend
    assert "mlflow:" in backend
    assert backend.count("condition: service_healthy") == 2
    assert "http://127.0.0.1:8000/api/health" in backend

    frontend = _service_block(compose, "frontend")
    assert "backend:" in frontend
    assert "condition: service_healthy" in frontend
    assert "http://127.0.0.1:5173" in frontend


def test_makefile_runs_docker_preflight_before_compose_up() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    docker_up_pattern = (
        r"(?m)^docker-up:\n\tpython3 scripts/check_docker_prereqs\.py\n"
        r"\tdocker compose up --build \$\(DOCKER_UP_FLAGS\)$"
    )

    assert re.search(docker_up_pattern, makefile)
    assert re.search(r"(?m)^eval-cached:\n\tcd \$\(BACKEND_DIR\).*--mode cached", makefile)


def test_deep_review_ci_runs_cached_eval() -> None:
    workflow = (ROOT / ".github" / "workflows" / "deep-review.yml").read_text(
        encoding="utf-8"
    )

    assert "run: make deep-review" in workflow
    assert "run: make eval-cached" in workflow


def test_manual_live_eval_workflow_requires_secret_and_uploads_reports() -> None:
    workflow = (ROOT / ".github" / "workflows" / "live-eval.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_dispatch:" in workflow
    assert "secrets.OPENAI_API_KEY" in workflow
    assert "make eval" in workflow
    assert "make live-quality-review" in workflow
    assert "make live-quality-smoke" in workflow
    assert "make check-secrets" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "reports/eval/**" in workflow
    assert "docs/reviews/live_quality_review.md" in workflow


def _request_context_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/probe")
    def probe(request: Request) -> dict[str, str | None]:
        return {
            "context_request_id": current_request_id(),
            "state_request_id": request.state.request_id,
        }

    return app


def _service_block(compose: str, service: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(service)}:\n(?P<body>.*?)(?=^  [a-zA-Z0-9_-]+:|\Z)",
        compose,
    )
    assert match is not None
    return match.group("body")
