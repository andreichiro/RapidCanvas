from __future__ import annotations

from app.api.rate_limit import InMemoryRateLimiter


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
