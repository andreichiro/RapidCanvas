"""Best-effort robots.txt policy for untrusted web fetches."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from urllib.parse import SplitResult, urlsplit, urlunsplit

import httpx

from app.clients.extraction import (
    Resolver,
    default_resolver,
    first_blocked_address_warning,
    validate_public_http_url,
)
from app.ml.boundary import boundary_text

ClientFactory = Callable[[], httpx.AsyncClient]


@dataclass(frozen=True)
class RobotsCheck:
    """Decision for a single candidate fetch target."""

    allowed: bool
    warnings: tuple[str, ...] = ()
    robots_url: str | None = None


@dataclass(frozen=True)
class _RobotsRule:
    path: str
    allow: bool


@dataclass(frozen=True)
class _RobotsGroup:
    agents: tuple[str, ...]
    rules: tuple[_RobotsRule, ...]


@dataclass(frozen=True)
class _CachedRobots:
    fetched_at: float
    groups: tuple[_RobotsGroup, ...] = ()
    warnings: tuple[str, ...] = ()


class RobotsPolicy:
    """Small-timeout cached robots.txt checker.

    Robots failures are best-effort: unavailable or malformed robots files do not
    make an otherwise public URL fetch fail. Explicit matching Disallow rules do.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 1.0,
        ttl_seconds: float = 3600.0,
        user_agent: str = "RapidCanvasBlueskyExplainer/0.1",
        client_factory: ClientFactory | None = None,
        resolver: Resolver = default_resolver,
        max_redirects: int = 2,
        max_bytes: int = 65_536,
    ) -> None:
        self._timeout_seconds = max(0.05, timeout_seconds)
        self._ttl_seconds = max(1.0, ttl_seconds)
        self._user_agent = user_agent
        self._client_factory = client_factory or self._default_client_factory
        self._resolver = resolver
        self._max_redirects = max(0, max_redirects)
        self._max_bytes = max(1024, max_bytes)
        self._cache: dict[str, _CachedRobots] = {}

    async def allowed(self, url: object) -> RobotsCheck:
        target_safety = validate_public_http_url(url, resolver=self._resolver)
        if not target_safety.allowed:
            return RobotsCheck(allowed=False, warnings=target_safety.warnings)

        origin, path, robots_url, warning = _target_parts(url)
        if warning:
            return RobotsCheck(allowed=False, warnings=(warning,))
        assert origin is not None
        assert path is not None
        assert robots_url is not None

        robots = await self._robots_for_origin(origin, robots_url)
        if robots.warnings:
            return RobotsCheck(allowed=True, warnings=robots.warnings, robots_url=robots_url)
        if _allowed_by_groups(robots.groups, self._user_agent, path):
            return RobotsCheck(allowed=True, robots_url=robots_url)
        return RobotsCheck(allowed=False, warnings=("robots_disallowed",), robots_url=robots_url)

    async def _robots_for_origin(self, origin: str, robots_url: str) -> _CachedRobots:
        cached = self._cache.get(origin)
        now = monotonic()
        if cached is not None and now - cached.fetched_at < self._ttl_seconds:
            return cached
        robots = await self._fetch_robots(robots_url)
        self._cache[origin] = robots
        return robots

    async def _fetch_robots(self, robots_url: str) -> _CachedRobots:
        try:
            async with self._client_factory() as client:
                return await self._fetch_robots_with_redirects(client, robots_url)
        except httpx.TimeoutException:
            return _CachedRobots(monotonic(), warnings=("robots_timeout",))
        except httpx.HTTPError as exc:
            return _CachedRobots(
                monotonic(),
                warnings=(f"robots_fetch_failed:{exc.__class__.__name__}",),
            )
        except Exception as exc:
            return _CachedRobots(
                monotonic(),
                warnings=(f"robots_fetch_failed:{exc.__class__.__name__}",),
            )

    async def _fetch_robots_with_redirects(
        self,
        client: httpx.AsyncClient,
        robots_url: str,
    ) -> _CachedRobots:
        current_url = robots_url
        for redirect_count in range(self._max_redirects + 1):
            safety = validate_public_http_url(current_url, resolver=self._resolver)
            if not safety.allowed:
                return _robots_fetch_blocked(safety.warnings)
            async with client.stream(
                "GET",
                current_url,
                follow_redirects=False,
                headers={"User-Agent": self._user_agent},
            ) as response:
                if warning := _peer_address_warning(response):
                    return _robots_fetch_blocked((warning,))
                if next_url := _robots_redirect(response, redirect_count, self._max_redirects):
                    if next_url.startswith("robots_"):
                        return _CachedRobots(monotonic(), warnings=(next_url,))
                    current_url = next_url
                    continue
                return await self._robots_response(response)
        return _CachedRobots(monotonic(), warnings=("robots_redirect_loop_unresolved",))

    async def _robots_response(self, response: httpx.Response) -> _CachedRobots:
        if response.status_code >= 400:
            return _CachedRobots(
                monotonic(),
                warnings=(f"robots_status:{response.status_code}",),
            )
        content_type = boundary_text(response.headers.get("content-type", "")).lower()
        if content_type and not content_type.startswith(("text/", "application/octet-stream")):
            return _CachedRobots(
                monotonic(),
                warnings=("robots_unsupported_content_type",),
            )
        text = await _read_limited_text(response, self._max_bytes)
        return _CachedRobots(monotonic(), groups=_parse_robots(text))

    def _default_client_factory(self) -> httpx.AsyncClient:
        timeout = httpx.Timeout(self._timeout_seconds)
        return httpx.AsyncClient(timeout=timeout, trust_env=False)


def _target_parts(url: object) -> tuple[str | None, str | None, str | None, str]:
    parsed, warning = _parse_target(url)
    if warning:
        return None, None, None, warning
    assert parsed is not None
    netloc = _robots_netloc(parsed.hostname or "", parsed.port)
    origin = urlunsplit((parsed.scheme.lower(), netloc, "", "", ""))
    robots_url = urlunsplit((parsed.scheme.lower(), netloc, "/robots.txt", "", ""))
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return origin, path, robots_url, ""


def _robots_fetch_blocked(warnings: tuple[str, ...]) -> _CachedRobots:
    safe_warnings = tuple(f"robots_fetch_blocked:{warning}" for warning in warnings)
    return _CachedRobots(monotonic(), warnings=safe_warnings)


def _robots_redirect(
    response: httpx.Response,
    redirect_count: int,
    max_redirects: int,
) -> str:
    location = response.headers.get("location")
    if not (300 <= response.status_code < 400 and location):
        return ""
    if redirect_count == max_redirects:
        return "robots_redirect_limit_exceeded"
    try:
        return boundary_text(response.url.join(location), "robots_redirect_url_text_failed")
    except (httpx.InvalidURL, ValueError):
        return "robots_malformed_redirect"


async def _read_limited_text(response: httpx.Response, max_bytes: int) -> str:
    content = bytearray()
    async for chunk in response.aiter_bytes():
        remaining = max_bytes - len(content)
        if remaining <= 0:
            break
        content.extend(chunk[:remaining])
    return bytes(content).decode(response.encoding or "utf-8", errors="replace")


def _peer_address_warning(response: httpx.Response) -> str:
    stream = response.extensions.get("network_stream")
    get_extra_info = getattr(stream, "get_extra_info", None)
    if not callable(get_extra_info):
        return ""
    try:
        peername = get_extra_info("peername")
    except Exception:
        return ""
    host = _peer_host(peername)
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return ""
    return first_blocked_address_warning([address])


def _peer_host(peername: object) -> str:
    if isinstance(peername, tuple) and peername:
        return boundary_text(peername[0], "robots_peer_host_text_failed")
    return peername if isinstance(peername, str) else ""


def _parse_target(url: object) -> tuple[SplitResult | None, str]:
    text = boundary_text(url, "robots_url_text_failed")
    try:
        parsed = urlsplit(text)
        _ = parsed.port
    except ValueError:
        return None, "robots_malformed_url"
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None, "robots_unsupported_url"
    return parsed, ""


def _robots_netloc(hostname: str, port: int | None) -> str:
    host = hostname.lower()
    netloc = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"{netloc}:{port}" if port is not None else netloc


def _parse_robots(text: str) -> tuple[_RobotsGroup, ...]:
    groups: list[_RobotsGroup] = []
    agents: list[str] = []
    rules: list[_RobotsRule] = []
    saw_rules = False

    for raw_line in text.splitlines():
        key, value = _robots_directive(raw_line)
        if not key:
            continue
        if key == "user-agent":
            if agents and saw_rules:
                groups.append(_RobotsGroup(tuple(agents), tuple(rules)))
                agents = []
                rules = []
                saw_rules = False
            if value:
                agents.append(value.lower())
            continue
        rule = _robots_rule(key, value, has_agents=bool(agents))
        if rule is None:
            continue
        saw_rules = True
        rules.append(rule)

    if agents:
        groups.append(_RobotsGroup(tuple(agents), tuple(rules)))
    return tuple(groups)


def _robots_directive(raw_line: str) -> tuple[str, str]:
    line = raw_line.split("#", maxsplit=1)[0].strip()
    if not line or ":" not in line:
        return "", ""
    key, raw_value = line.split(":", maxsplit=1)
    return key.strip().lower(), raw_value.strip()


def _robots_rule(key: str, value: str, *, has_agents: bool) -> _RobotsRule | None:
    if key not in {"allow", "disallow"} or not has_agents:
        return None
    if key == "disallow" and value == "":
        return None
    return _RobotsRule(path=value or "/", allow=key == "allow")


def _allowed_by_groups(
    groups: tuple[_RobotsGroup, ...],
    user_agent: str,
    path: str,
) -> bool:
    if not groups:
        return True
    rules = _matching_rules(groups, user_agent)
    matched = [rule for rule in rules if _rule_matches(rule.path, path)]
    if not matched:
        return True
    best_length = max(_rule_specificity(rule.path) for rule in matched)
    best = [rule for rule in matched if _rule_specificity(rule.path) == best_length]
    return any(rule.allow for rule in best)


def _matching_rules(groups: tuple[_RobotsGroup, ...], user_agent: str) -> list[_RobotsRule]:
    ua = user_agent.lower()
    ua_token = ua.split("/", maxsplit=1)[0]
    direct: list[tuple[int, tuple[_RobotsRule, ...]]] = []
    wildcard: list[_RobotsRule] = []
    for group in groups:
        if any(agent == "*" for agent in group.agents):
            wildcard.extend(group.rules)
            continue
        matches = [
            agent
            for agent in group.agents
            if agent and (agent in ua or agent in ua_token or ua_token in agent)
        ]
        if matches:
            direct.append((max(len(agent) for agent in matches), group.rules))
    if not direct:
        return wildcard
    best_specificity = max(specificity for specificity, _rules in direct)
    return [
        rule
        for specificity, rules in direct
        if specificity == best_specificity
        for rule in rules
    ]


def _rule_matches(pattern: str, path: str) -> bool:
    if not pattern:
        return False
    if "*" not in pattern and not pattern.endswith("$"):
        return path.startswith(pattern)
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = re.escape(body).replace(r"\*", ".*")
    if anchored:
        regex = f"{regex}$"
    return re.match(regex, path) is not None


def _rule_specificity(pattern: str) -> int:
    return len(pattern.replace("*", "").removesuffix("$"))
