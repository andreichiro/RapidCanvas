"""Safe linked-page fetching for untrusted web evidence."""

from __future__ import annotations

import hashlib
import ipaddress
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from app.clients.extraction import (
    Resolver,
    default_resolver,
    extract_page_text,
    first_blocked_address_warning,
    validate_public_http_url,
)
from app.clients.robots import RobotsCheck, RobotsPolicy
from app.guardrails.prompt_injection import sanitize_context_document
from app.ml.boundary import boundary_text
from app.schemas.domain import ContextDocument

ClientFactory = Callable[[], httpx.AsyncClient]

_SUPPORTED_CONTENT_TYPES = (
    "text/html", "text/plain", "application/xhtml+xml", "application/xml", "text/xml"
)


@dataclass(frozen=True)
class FetchResult:
    document: ContextDocument | None
    warnings: tuple[str, ...] = ()
    blocked: bool = False
    status_code: int | None = None


@dataclass(frozen=True)
class _FetchStep:
    result: FetchResult | None = None
    next_url: str | None = None


class LinkedPageFetcher:
    def __init__(
        self,
        *,
        timeout_seconds: float = 8.0,
        max_bytes: int = 200_000,
        max_redirects: int = 3,
        resolver: Resolver = default_resolver,
        client_factory: ClientFactory | None = None,
        robots_policy: RobotsPolicy | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self._resolver = resolver
        self._client_factory = client_factory or self._default_client_factory
        self._robots_policy = (
            robots_policy
            if robots_policy is not None
            else RobotsPolicy(timeout_seconds=min(timeout_seconds, 1.0), resolver=resolver)
            if client_factory is None
            else None
        )

    @property
    def resolver(self) -> Resolver:
        return self._resolver

    async def fetch(self, url: object, source_id: str | None = None) -> FetchResult:
        warnings: list[str] = []
        try:
            async with self._client_factory() as client:
                return await self._fetch_with_redirects(client, url, source_id, warnings)
        except httpx.RemoteProtocolError as exc:
            malformed = "location header" in boundary_text(exc).lower()
            error_name = exc.__class__.__name__
            warning = "blocked_malformed_url" if malformed else f"http_error:{error_name}"
            return FetchResult(document=None, warnings=(warning,), blocked=malformed)
        except httpx.TimeoutException:
            return FetchResult(document=None, warnings=("timeout",))
        except httpx.HTTPError as exc:
            return FetchResult(document=None, warnings=(f"http_error:{exc.__class__.__name__}",))
        except Exception as exc:
            return FetchResult(document=None, warnings=(f"fetch_failed:{exc.__class__.__name__}",))

    async def _fetch_with_redirects(
        self,
        client: httpx.AsyncClient,
        url: object,
        source_id: str | None,
        warnings: list[str],
    ) -> FetchResult:
        current_url = url
        for redirect_count in range(self._max_redirects + 1):
            safety = validate_public_http_url(current_url, resolver=self._resolver)
            if not safety.allowed:
                return FetchResult(document=None, warnings=safety.warnings, blocked=True)
            current_url = _url_text(current_url)

            robots_result = await self._robots_check(current_url)
            if robots_result is not None:
                for warning in robots_result.warnings:
                    if warning not in warnings:
                        warnings.append(warning)
                if not robots_result.allowed:
                    return FetchResult(document=None, warnings=tuple(warnings))

            step = await self._fetch_step(client, current_url, source_id, warnings, redirect_count)
            if step.result is not None:
                return step.result
            if step.next_url is not None:
                current_url = step.next_url
        return FetchResult(document=None, warnings=("redirect_loop_unresolved",))

    async def _robots_check(self, url: str) -> RobotsCheck | None:
        if self._robots_policy is None:
            return None
        return await self._robots_policy.allowed(url)

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
            if peer_warning := _peer_address_warning(response):
                return _FetchStep(
                    result=FetchResult(
                        document=None,
                        warnings=tuple(warnings + [peer_warning]),
                        blocked=True,
                        status_code=response.status_code,
                    )
                )
            redirect_step = self._redirect_step(response, warnings, redirect_count)
            if redirect_step is not None:
                return redirect_step
            return _FetchStep(
                result=await self._response_result(
                    response,
                    source_id,
                    warnings,
                    redirect_count=redirect_count,
                )
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
        try:
            next_url = boundary_text(response.url.join(location), "redirect_url_text_failed")
        except (httpx.InvalidURL, ValueError):
            result = FetchResult(
                document=None,
                warnings=tuple(warnings + ["blocked_malformed_url"]),
                blocked=True,
                status_code=response.status_code,
            )
            return _FetchStep(result=result)
        warnings.append("redirect_validated")
        return _FetchStep(next_url=next_url)

    async def _response_result(
        self,
        response: httpx.Response,
        source_id: str | None,
        warnings: list[str],
        *,
        redirect_count: int,
    ) -> FetchResult:
        status_result = _status_or_content_type_result(response, warnings)
        if status_result is not None:
            return status_result

        content_type = _content_type(response)
        raw = await self._read_limited(response, warnings)
        try:
            title, text = extract_page_text(raw, content_type=content_type)
        except Exception as exc:
            return FetchResult(
                document=None,
                warnings=tuple(warnings + [f"extraction_failed:{exc.__class__.__name__}"]),
                status_code=response.status_code,
            )
        if not text:
            return FetchResult(
                document=None,
                warnings=tuple(warnings + ["empty_extracted_text"]),
                status_code=response.status_code,
            )
        document = _build_web_document(
            response,
            source_id,
            content_type,
            title,
            text,
            warnings,
            redirect_count=redirect_count,
        )
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
        return httpx.AsyncClient(timeout=httpx.Timeout(self._timeout_seconds), trust_env=False)


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
    return boundary_text(response.headers.get("content-type", "")).split(";")[0].lower()


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
    if not host:
        return ""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return ""
    return first_blocked_address_warning([address])


def _peer_host(peername: object) -> str:
    if isinstance(peername, tuple) and peername:
        return boundary_text(peername[0], "peer_host_text_failed")
    if isinstance(peername, str):
        return peername
    return ""


def _build_web_document(
    response: httpx.Response,
    source_id: str | None,
    content_type: str,
    title: str,
    text: str,
    warnings: list[str],
    *,
    redirect_count: int,
) -> ContextDocument:
    response_url = boundary_text(response.url, "response_url_text_failed")
    document_id = boundary_text(source_id, "source_id_text_failed")
    if not document_id:
        document_id = f"WEB-{_stable_hash(response_url)[:12]}"
    return ContextDocument(
        id=document_id,
        source_type="web",
        title=title or response_url,
        url=response_url,
        text=text,
        metadata={
            "canonical_domain": _canonical_domain(response_url),
            "content_type": content_type or "unknown",
            "fetch_success": True,
            "fetch_status": response.status_code,
            "status_code": response.status_code,
            "extracted_length": len(text.strip()),
            "redirect_count": redirect_count,
            "warnings": list(warnings),
        },
    )


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_domain(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def _url_text(url: object) -> str:
    if isinstance(url, bytes | bytearray):
        return bytes(url).decode("utf-8", errors="replace")
    return boundary_text(url, "url_text_failed")
