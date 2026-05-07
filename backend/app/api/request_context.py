"""Request ID context, client attribution, and sanitized route logging."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Sequence
from contextvars import ContextVar

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_current_request_id: ContextVar[str | None] = ContextVar("rapidcanvas_request_id", default=None)
logger = logging.getLogger("app.api.request")
_REQUEST_LOG_HANDLER_MARKER = "_rapidcanvas_request_log_handler"


def configure_request_logging() -> None:
    """Ensure structured request logs are emitted by local/container servers."""

    logger.setLevel(logging.INFO)
    for handler in logger.handlers:
        if getattr(handler, _REQUEST_LOG_HANDLER_MARKER, False):
            return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.setLevel(logging.INFO)
    setattr(handler, _REQUEST_LOG_HANDLER_MARKER, True)
    logger.addHandler(handler)


def current_request_id() -> str | None:
    """Return the request ID bound to this request context, if any."""

    return _current_request_id.get()


def new_request_id() -> str:
    """Generate a compact opaque request ID."""

    return uuid.uuid4().hex


def sanitize_request_id(value: str | None) -> str:
    """Accept safe caller-provided request IDs and replace unsafe values."""

    candidate = (value or "").strip()
    return candidate if _REQUEST_ID_RE.fullmatch(candidate) else new_request_id()


def client_ip_for_request(request: Request, trusted_proxy_hosts: Sequence[str]) -> str:
    """Use X-Forwarded-For only when the direct peer is a trusted proxy."""

    client_host = request.client.host if request.client else "unknown"
    if client_host not in set(trusted_proxy_hosts):
        return client_host
    forwarded = request.headers.get("x-forwarded-for", "")
    first_hop = forwarded.split(",", 1)[0].strip()
    return first_hop or client_host


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request ID and write sanitized one-line route logs."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        trusted_proxy_hosts: Sequence[str] = (),
    ) -> None:
        super().__init__(app)
        self._trusted_proxy_hosts = tuple(trusted_proxy_hosts)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = sanitize_request_id(request.headers.get(REQUEST_ID_HEADER))
        token = _current_request_id.set(request_id)
        request.state.request_id = request_id
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            latency_ms = int((time.perf_counter() - started) * 1000)
            _log_request(request, request_id, status_code, latency_ms, self._trusted_proxy_hosts)
            _current_request_id.reset(token)


def _log_request(
    request: Request,
    request_id: str,
    status_code: int,
    latency_ms: int,
    trusted_proxy_hosts: Sequence[str],
) -> None:
    payload = {
        "event": "http_request",
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "status_code": status_code,
        "latency_ms": latency_ms,
        "client_host": client_ip_for_request(request, trusted_proxy_hosts),
    }
    logger.info(json.dumps(payload, sort_keys=True))
