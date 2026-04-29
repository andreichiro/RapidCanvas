"""Safe linked-page fetching for untrusted web evidence."""

from __future__ import annotations

import hashlib
import ipaddress
import socket
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.clients.extraction import extract_page_text
from app.guardrails.prompt_injection import sanitize_context_document
from app.schemas.domain import ContextDocument

Resolver = Callable[[str], Sequence[str]]
ClientFactory = Callable[[], httpx.AsyncClient]

_LOCAL_HOSTNAMES = {"localhost", "localhost.localdomain"}
_SUPPORTED_CONTENT_TYPES = (
    "text/html",
    "text/plain",
    "application/xhtml+xml",
    "application/xml",
    "text/xml",
)


@dataclass(frozen=True)
class UrlSafetyResult:
    """Result of a public-web URL allowlist check."""

    allowed: bool
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class FetchResult:
    """Outcome of a linked-page fetch."""

    document: ContextDocument | None
    warnings: tuple[str, ...] = ()
    blocked: bool = False
    status_code: int | None = None


@dataclass(frozen=True)
class _FetchStep:
    result: FetchResult | None = None
    next_url: str | None = None


def default_resolver(hostname: str) -> Sequence[str]:
    """Resolve hostnames for SSRF checks."""

    return tuple({str(item[4][0]) for item in socket.getaddrinfo(hostname, None)})


def validate_public_http_url(
    url: str,
    resolver: Resolver = default_resolver,
) -> UrlSafetyResult:
    """Allow only public HTTP(S) URLs and block local/private/link-local targets."""

    parsed = urlsplit(url)
    basic_warning = _basic_url_warning(parsed.scheme, parsed.hostname)
    if basic_warning:
        return UrlSafetyResult(False, (basic_warning,))

    hostname = parsed.hostname.rstrip(".").lower() if parsed.hostname else ""
    local_warning = _local_hostname_warning(hostname)
    if local_warning:
        return UrlSafetyResult(False, (local_warning,))

    addresses, resolution_warning = _resolve_addresses(hostname, resolver)
    if resolution_warning:
        return UrlSafetyResult(False, (resolution_warning,))

    blocked_warning = _first_blocked_address_warning(addresses)
    if blocked_warning:
        return UrlSafetyResult(False, (blocked_warning,))
    return UrlSafetyResult(True)


def _basic_url_warning(scheme: str, hostname: str | None) -> str:
    if scheme not in {"http", "https"}:
        return f"blocked_unsupported_scheme:{scheme or 'none'}"
    if not hostname:
        return "blocked_missing_hostname"
    return ""


def _local_hostname_warning(hostname: str) -> str:
    if hostname in _LOCAL_HOSTNAMES or hostname.endswith(".localhost"):
        return f"blocked_local_hostname:{hostname}"
    return ""


def _resolve_addresses(
    hostname: str,
    resolver: Resolver,
) -> tuple[list[ipaddress.IPv4Address | ipaddress.IPv6Address], str]:
    try:
        return [ipaddress.ip_address(hostname)], ""
    except ValueError:
        try:
            return [ipaddress.ip_address(address) for address in resolver(hostname)], ""
        except OSError as exc:
            return [], f"dns_resolution_failed:{hostname}:{exc}"
        except ValueError as exc:
            return [], f"dns_resolution_invalid:{hostname}:{exc}"


def _first_blocked_address_warning(
    addresses: Sequence[ipaddress.IPv4Address | ipaddress.IPv6Address],
) -> str:
    for address in addresses:
        if not address.is_global:
            return f"blocked_non_public_ip:{address}"
    return ""


class LinkedPageFetcher:
    """Fetch public web pages with SSRF guards, content checks, and extraction."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 8.0,
        max_bytes: int = 200_000,
        max_redirects: int = 3,
        resolver: Resolver = default_resolver,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self._resolver = resolver
        self._client_factory = client_factory or self._default_client_factory

    @property
    def resolver(self) -> Resolver:
        """Return the resolver used for URL safety checks."""

        return self._resolver

    async def fetch(self, url: str, source_id: str | None = None) -> FetchResult:
        """Fetch and extract a public page, returning warnings instead of raising."""

        warnings: list[str] = []
        try:
            async with self._client_factory() as client:
                return await self._fetch_with_redirects(client, url, source_id, warnings)
        except httpx.TimeoutException:
            return FetchResult(document=None, warnings=("timeout",))
        except httpx.HTTPError as exc:
            return FetchResult(document=None, warnings=(f"http_error:{exc.__class__.__name__}",))

    async def _fetch_with_redirects(
        self,
        client: httpx.AsyncClient,
        url: str,
        source_id: str | None,
        warnings: list[str],
    ) -> FetchResult:
        current_url = url
        for redirect_count in range(self._max_redirects + 1):
            safety = validate_public_http_url(current_url, resolver=self._resolver)
            if not safety.allowed:
                return FetchResult(document=None, warnings=safety.warnings, blocked=True)
            warnings.extend(safety.warnings)

            step = await self._fetch_step(client, current_url, source_id, warnings, redirect_count)
            if step.result is not None:
                return step.result
            if step.next_url is not None:
                current_url = step.next_url
        return FetchResult(document=None, warnings=("redirect_loop_unresolved",))

    async def _fetch_step(
        self,
        client: httpx.AsyncClient,
        url: str,
        source_id: str | None,
        warnings: list[str],
        redirect_count: int,
    ) -> _FetchStep:
        async with client.stream(
            "GET",
            url,
            follow_redirects=False,
            headers={"User-Agent": "RapidCanvasBlueskyExplainer/0.1"},
        ) as response:
            redirect_step = self._redirect_step(response, warnings, redirect_count)
            if redirect_step is not None:
                return redirect_step
            return _FetchStep(
                result=await self._response_result(response, source_id, warnings)
            )

    def _redirect_step(
        self,
        response: httpx.Response,
        warnings: list[str],
        redirect_count: int,
    ) -> _FetchStep | None:
        location = response.headers.get("location")
        if not (300 <= response.status_code < 400 and location):
            return None
        if redirect_count == self._max_redirects:
            result = FetchResult(
                document=None,
                warnings=tuple(warnings + ["redirect_limit_exceeded"]),
                status_code=response.status_code,
            )
            return _FetchStep(result=result)
        warnings.append("redirect_validated")
        return _FetchStep(next_url=str(response.url.join(location)))

    async def _response_result(
        self,
        response: httpx.Response,
        source_id: str | None,
        warnings: list[str],
    ) -> FetchResult:
        status_result = _status_or_content_type_result(response, warnings)
        if status_result is not None:
            return status_result

        content_type = _content_type(response)
        raw = await self._read_limited(response, warnings)
        title, text = extract_page_text(raw, content_type=content_type)
        if not text:
            return FetchResult(
                document=None,
                warnings=tuple(warnings + ["empty_extracted_text"]),
                status_code=response.status_code,
            )
        document = _build_web_document(response, source_id, content_type, title, text, warnings)
        sanitized_document, scan = sanitize_context_document(document)
        metadata = {
            **sanitized_document.metadata,
            "warnings": list(warnings),
            "prompt_injection_flags": list(scan.flags),
        }
        return FetchResult(
            document=sanitized_document.model_copy(update={"metadata": metadata}),
            warnings=tuple(warnings),
            status_code=response.status_code,
        )

    async def _read_limited(self, response: httpx.Response, warnings: list[str]) -> str:
        content = bytearray()
        async for chunk in response.aiter_bytes():
            remaining = self._max_bytes - len(content)
            if remaining <= 0:
                warnings.append("content_truncated")
                break
            if len(chunk) > remaining:
                content.extend(chunk[:remaining])
                warnings.append("content_truncated")
                break
            content.extend(chunk)
        return bytes(content).decode(response.encoding or "utf-8", errors="replace")

    def _default_client_factory(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=httpx.Timeout(self._timeout_seconds))


def _status_or_content_type_result(
    response: httpx.Response,
    warnings: list[str],
) -> FetchResult | None:
    if response.status_code >= 400:
        return FetchResult(
            document=None,
            warnings=tuple(warnings + [f"http_status:{response.status_code}"]),
            status_code=response.status_code,
        )
    content_type = _content_type(response)
    if content_type and content_type not in _SUPPORTED_CONTENT_TYPES:
        return FetchResult(
            document=None,
            warnings=tuple(warnings + [f"unsupported_content_type:{content_type}"]),
            status_code=response.status_code,
        )
    return None


def _content_type(response: httpx.Response) -> str:
    return str(response.headers.get("content-type", "")).split(";")[0].lower()


def _build_web_document(
    response: httpx.Response,
    source_id: str | None,
    content_type: str,
    title: str,
    text: str,
    warnings: list[str],
) -> ContextDocument:
    document_id = source_id or f"WEB-{_stable_hash(str(response.url))[:12]}"
    return ContextDocument(
        id=document_id,
        source_type="web",
        title=title or str(response.url),
        url=str(response.url),
        text=text,
        metadata={
            "content_type": content_type or "unknown",
            "status_code": response.status_code,
            "warnings": list(warnings),
        },
    )


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
