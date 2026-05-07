"""Small in-process rate limiter for local and single-instance deployments."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable, Sequence
from time import monotonic

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.api.request_context import client_ip_for_request


class InMemoryRateLimiter:
    """Bound request counts per key over a sliding time window."""

    def __init__(
        self,
        *,
        max_requests: int,
        window_seconds: int,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._max_requests = max(1, max_requests)
        self._window_seconds = max(1, window_seconds)
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        """Return whether the key still has quota in the current window."""

        now = self._clock()
        window_start = now - self._window_seconds
        hits = self._hits[key]
        while hits and hits[0] <= window_start:
            hits.popleft()
        if len(hits) >= self._max_requests:
            return False
        hits.append(now)
        return True


class ExplainRateLimitMiddleware(BaseHTTPMiddleware):
    """Apply rate limiting only to the expensive explain endpoint."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        api_prefix: str,
        max_requests: int,
        window_seconds: int,
        trusted_proxy_hosts: Sequence[str] = (),
    ) -> None:
        super().__init__(app)
        self._explain_path = f"{api_prefix.rstrip('/')}/explain"
        self._trusted_proxy_hosts = tuple(trusted_proxy_hosts)
        self._limiter = InMemoryRateLimiter(
            max_requests=max_requests,
            window_seconds=window_seconds,
        )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Reject excess explain calls with a structured 429 response."""

        if request.method == "POST" and request.url.path == self._explain_path:
            client_host = client_ip_for_request(request, self._trusted_proxy_hosts)
            if not self._limiter.allow(client_host):
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": {
                            "code": "rate_limited",
                            "message": "Too many explain requests. Please wait and try again.",
                        }
                    },
                )
        response = await call_next(request)
        return response
