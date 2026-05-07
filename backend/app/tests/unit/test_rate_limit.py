from __future__ import annotations

from starlette.requests import Request

from app.api.rate_limit import InMemoryRateLimiter
from app.api.request_context import client_ip_for_request


def test_in_memory_rate_limiter_blocks_after_window_quota() -> None:
    now = 100.0

    def clock() -> float:
        return now

    limiter = InMemoryRateLimiter(max_requests=2, window_seconds=10, clock=clock)

    assert limiter.allow("client-a")
    assert limiter.allow("client-a")
    assert not limiter.allow("client-a")


def test_in_memory_rate_limiter_expires_old_hits() -> None:
    now = 100.0

    def clock() -> float:
        return now

    limiter = InMemoryRateLimiter(max_requests=1, window_seconds=10, clock=clock)

    assert limiter.allow("client-a")
    assert not limiter.allow("client-a")
    now = 111.0
    assert limiter.allow("client-a")


def test_in_memory_rate_limiter_keeps_clients_separate() -> None:
    limiter = InMemoryRateLimiter(max_requests=1, window_seconds=10, clock=lambda: 100.0)

    assert limiter.allow("client-a")
    assert limiter.allow("client-b")
    assert not limiter.allow("client-a")


def test_client_ip_ignores_forwarded_for_without_trusted_proxy() -> None:
    request = _request(client_host="203.0.113.10", forwarded_for="198.51.100.9")

    assert client_ip_for_request(request, trusted_proxy_hosts=()) == "203.0.113.10"


def test_client_ip_uses_forwarded_for_from_trusted_proxy() -> None:
    request = _request(client_host="10.0.0.10", forwarded_for="198.51.100.9, 203.0.113.8")

    assert client_ip_for_request(request, trusted_proxy_hosts=("10.0.0.10",)) == "198.51.100.9"


def _request(*, client_host: str, forwarded_for: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/explain",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": (client_host, 12345),
            "headers": [(b"x-forwarded-for", forwarded_for.encode("ascii"))],
        }
    )
