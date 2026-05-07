from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from app.clients.robots import RobotsPolicy


def public_resolver(hostname: str) -> tuple[str, ...]:
    assert hostname == "example.com"
    return ("93.184.216.34",)


def client_factory(
    handler: Callable[[httpx.Request], httpx.Response],
) -> Callable[[], httpx.AsyncClient]:
    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    return factory


class FakeNetworkStream:
    def __init__(self, peername: object) -> None:
        self._peername = peername

    def get_extra_info(self, name: str) -> object:
        return self._peername if name == "peername" else None


@pytest.mark.asyncio
async def test_robots_policy_disallows_matching_user_agent_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://example.com/robots.txt"
        return httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            text="User-agent: *\nDisallow: /private\n",
            request=request,
        )

    policy = RobotsPolicy(client_factory=client_factory(handler), resolver=public_resolver)

    result = await policy.allowed("https://example.com/private/page?token=secret")

    assert result.allowed is False
    assert result.warnings == ("robots_disallowed",)
    assert result.robots_url == "https://example.com/robots.txt"
    assert all("token=secret" not in warning for warning in result.warnings)


@pytest.mark.asyncio
async def test_robots_policy_allows_longer_allow_rule_over_broader_disallow() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="User-agent: *\nDisallow: /private\nAllow: /private/public\n",
            request=request,
        )

    policy = RobotsPolicy(client_factory=client_factory(handler), resolver=public_resolver)

    allowed = await policy.allowed("https://example.com/private/public/post")
    disallowed = await policy.allowed("https://example.com/private/internal")

    assert allowed.allowed is True
    assert disallowed.allowed is False
    assert disallowed.warnings == ("robots_disallowed",)


@pytest.mark.asyncio
async def test_robots_policy_prefers_specific_agent_group_over_wildcard() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=(
                "User-agent: *\n"
                "Disallow: /\n"
                "User-agent: RapidCanvasBlueskyExplainer\n"
                "Allow: /\n"
            ),
            request=request,
        )

    policy = RobotsPolicy(client_factory=client_factory(handler), resolver=public_resolver)

    result = await policy.allowed("https://example.com/context")

    assert result.allowed is True
    assert result.warnings == ()


@pytest.mark.asyncio
async def test_robots_policy_prefers_most_specific_agent_group() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=(
                "User-agent: RapidCanvas\n"
                "Allow: /context\n"
                "User-agent: RapidCanvasBlueskyExplainer\n"
                "Disallow: /context\n"
            ),
            request=request,
        )

    policy = RobotsPolicy(client_factory=client_factory(handler), resolver=public_resolver)

    result = await policy.allowed("https://example.com/context")

    assert result.allowed is False
    assert result.warnings == ("robots_disallowed",)


@pytest.mark.asyncio
async def test_robots_policy_caches_origin_rules() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            text="User-agent: *\nDisallow: /blocked\n",
            request=request,
        )

    policy = RobotsPolicy(
        client_factory=client_factory(handler),
        resolver=public_resolver,
        ttl_seconds=3600,
    )

    first = await policy.allowed("https://example.com/blocked")
    second = await policy.allowed("https://example.com/allowed")

    assert calls == 1
    assert first.allowed is False
    assert second.allowed is True


@pytest.mark.asyncio
async def test_robots_policy_failures_are_best_effort_warnings() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow robots", request=request)

    policy = RobotsPolicy(client_factory=client_factory(handler), resolver=public_resolver)

    result = await policy.allowed("https://example.com/context")

    assert result.allowed is True
    assert result.warnings == ("robots_timeout",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "warning"),
    [
        ("http://127.0.0.1/admin", "blocked_non_public_ip:127.0.0.1"),
        ("http://localhost/admin", "blocked_local_hostname:localhost"),
        ("file:///etc/passwd", "blocked_unsupported_scheme:file"),
        ("https://user:pass@example.com/context", "blocked_url_userinfo"),
    ],
)
async def test_robots_policy_blocks_unsafe_target_before_fetching_robots(
    url: str,
    warning: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unsafe target should not fetch robots.txt: {request.url}")

    policy = RobotsPolicy(client_factory=client_factory(handler), resolver=public_resolver)

    result = await policy.allowed(url)

    assert result.allowed is False
    assert result.warnings == (warning,)


@pytest.mark.asyncio
async def test_robots_policy_blocks_private_redirect_without_following() -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(
            302,
            headers={"location": "http://127.0.0.1/robots.txt"},
            request=request,
        )

    policy = RobotsPolicy(client_factory=client_factory(handler), resolver=public_resolver)

    result = await policy.allowed("https://example.com/context")

    assert requested_urls == ["https://example.com/robots.txt"]
    assert result.allowed is True
    assert result.warnings == ("robots_fetch_blocked:blocked_non_public_ip:127.0.0.1",)


@pytest.mark.asyncio
async def test_robots_policy_blocks_private_peer_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="User-agent: *\nDisallow: /\n",
            request=request,
            extensions={"network_stream": FakeNetworkStream(("127.0.0.1", 443))},
        )

    policy = RobotsPolicy(client_factory=client_factory(handler), resolver=public_resolver)

    result = await policy.allowed("https://example.com/context")

    assert result.allowed is True
    assert result.warnings == ("robots_fetch_blocked:blocked_non_public_ip:127.0.0.1",)
