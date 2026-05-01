from __future__ import annotations

import importlib
import ipaddress
import re
import socket
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import SplitResult, urlsplit, urlunsplit

from app.guardrails.prompt_injection import (
    PromptInjectionScanResult,
    sanitize_context_document,
    sanitize_untrusted_text,
)
from app.ml.boundary import boundary_attr
from app.ml.boundary import boundary_text as bt
from app.ml.vector_payloads import metadata_mapping
from app.schemas.domain import ContextDocument

Resolver = Callable[[str], Sequence[str]]
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

_LOCAL_HOSTNAMES = {"localhost", "localhost.localdomain"}
_URL_FORBIDDEN_CHARS_RE = re.compile(r"[\s\x00-\x1f\x7f]")


@dataclass(frozen=True)
class UrlSafetyResult:
    allowed: bool
    warnings: tuple[str, ...] = ()


def default_resolver(hostname: str) -> Sequence[str]:
    return tuple({str(item[4][0]) for item in socket.getaddrinfo(hostname, None)})


def validate_public_http_url(url: object, resolver: Resolver = default_resolver) -> UrlSafetyResult:
    parsed, warning = _parse_url(url)
    if warning:
        return UrlSafetyResult(False, (warning,))
    assert parsed is not None
    if warning := _basic_url_warning(parsed.scheme, parsed.hostname):
        return UrlSafetyResult(False, (warning,))
    if _has_userinfo(parsed):
        return UrlSafetyResult(False, ("blocked_url_userinfo",))
    if warning := _host_warning(parsed, resolve=True, resolver=resolver):
        return UrlSafetyResult(False, (warning,))
    return UrlSafetyResult(True)


def validate_source_url_metadata(
    url: object,
    *,
    allow_at_uri: bool = False,
    resolver: Resolver | None = None,
) -> UrlSafetyResult:
    parsed, warning = _parse_url(url, validate_port=False)
    if warning:
        return UrlSafetyResult(False, (warning,))
    assert parsed is not None
    if parsed.scheme == "at":
        warning = _at_uri_source_warning(parsed, allow_at_uri=allow_at_uri)
    else:
        warning = _http_source_warning(parsed, resolver=resolver)
    return UrlSafetyResult(False, (warning,)) if warning else UrlSafetyResult(True)


def redact_url_for_warning(url: object) -> str:
    parsed, warning = _parse_url(url)
    if warning:
        return "<malformed_url>"
    assert parsed is not None
    hostname = parsed.hostname or ""
    if not hostname:
        return "<missing_hostname>"
    host = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
    netloc = f"{host}:{parsed.port}" if parsed.port is not None else host
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def first_blocked_address_warning(addresses: Sequence[IPAddress]) -> str:
    for address in addresses:
        if not address.is_global:
            return f"blocked_non_public_ip:{address}"
    return ""


def _parse_url(url: object, *, validate_port: bool = True) -> tuple[SplitResult | None, str]:
    text, warning = _coerce_url(url)
    if warning:
        return None, warning
    if _URL_FORBIDDEN_CHARS_RE.search(text):
        return None, "blocked_malformed_url"
    try:
        parsed = urlsplit(text)
    except ValueError:
        return None, "blocked_malformed_url"
    if validate_port and (warning := _port_warning(parsed)):
        return None, warning
    return parsed, ""


def _coerce_url(url: object) -> tuple[str, str]:
    if isinstance(url, str):
        return url, ""
    if isinstance(url, bytes | bytearray):
        return bytes(url).decode("utf-8", errors="replace"), ""
    return "", "blocked_malformed_url"


def _port_warning(parsed: SplitResult) -> str:
    try:
        _ = parsed.port
    except ValueError:
        return "blocked_malformed_url"
    return ""


def _basic_url_warning(scheme: str, hostname: str | None) -> str:
    if scheme not in {"http", "https"}:
        return f"blocked_unsupported_scheme:{scheme or 'none'}"
    if not hostname:
        return "blocked_missing_hostname"
    return ""


def _at_uri_source_warning(parsed: SplitResult, *, allow_at_uri: bool) -> str:
    if not allow_at_uri:
        return "blocked_unsupported_scheme:at"
    return "" if parsed.netloc and parsed.path else "blocked_malformed_url"


def _http_source_warning(parsed: SplitResult, *, resolver: Resolver | None = None) -> str:
    userinfo_warning = "blocked_url_userinfo" if _has_userinfo(parsed) else ""
    return (
        _port_warning(parsed)
        or _basic_url_warning(parsed.scheme, parsed.hostname)
        or userinfo_warning
        or _host_warning(
            parsed,
            resolve=resolver is not None,
            resolver=resolver or default_resolver,
        )
    )


def _has_userinfo(parsed: SplitResult) -> bool:
    return parsed.username is not None or parsed.password is not None


def _host_warning(
    parsed: SplitResult,
    *,
    resolve: bool,
    resolver: Resolver = default_resolver,
) -> str:
    hostname = parsed.hostname.rstrip(".").lower() if parsed.hostname else ""
    if hostname in _LOCAL_HOSTNAMES or hostname.endswith(".localhost"):
        return f"blocked_local_hostname:{hostname}"
    addresses, warning = _addresses_for_host(hostname, resolver if resolve else None)
    return warning or first_blocked_address_warning(addresses)


def _addresses_for_host(
    hostname: str,
    resolver: Resolver | None,
) -> tuple[list[IPAddress], str]:
    if address := _parse_hostname_ip(hostname):
        return [address], ""
    if resolver is None:
        return [], ""
    try:
        resolved = tuple(resolver(hostname))
    except OSError as exc:
        return [], f"dns_resolution_failed:{hostname}:{exc}"
    except Exception as exc:
        return [], f"dns_resolution_failed:{hostname}:{exc}"
    if not resolved:
        return [], f"dns_resolution_empty:{hostname}"
    try:
        return [ipaddress.ip_address(address) for address in resolved], ""
    except Exception as exc:
        return [], f"dns_resolution_invalid:{hostname}:{exc}"


def _parse_hostname_ip(hostname: str) -> IPAddress | None:
    try:
        return ipaddress.ip_address(hostname)
    except ValueError:
        try:
            return ipaddress.ip_address(socket.inet_aton(hostname))
        except OSError:
            return None


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0
        self.title = ""
        self._in_title = False
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.lower() in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if tag.lower() == "title":
            self._in_title = False
            self.title = sanitize_untrusted_text(" ".join(self._title_parts), max_chars=200)

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self._title_parts.append(data)
        self._parts.append(data)

    @property
    def text(self) -> str:
        return sanitize_untrusted_text(" ".join(self._parts))


def extract_page_text(raw: str, content_type: str = "text/html") -> tuple[str, str]:
    if content_type in {"text/plain", "text/xml", "application/xml"}:
        return "", sanitize_untrusted_text(raw)

    trafilatura_text = _extract_with_trafilatura(raw)
    if trafilatura_text:
        return _extract_title(raw), sanitize_untrusted_text(trafilatura_text)

    soup_title, soup_text = _extract_with_bs4(raw)
    if soup_text:
        return soup_title, soup_text

    parser = _TextExtractor()
    parser.feed(raw)
    return parser.title, parser.text


def sanitize_search_hit_document(
    document: ContextDocument,
    hit: dict[str, object],
    *,
    query: str,
    index: int,
    fetch_fallback: bool = False,
) -> tuple[ContextDocument, PromptInjectionScanResult]:
    base_title = hit.get("title") or boundary_attr(document, "title", "document_title_field_failed")
    title = sanitize_untrusted_text(bt(base_title), max_chars=200)
    snippet = sanitize_untrusted_text(
        bt(hit.get("body") or hit.get("snippet") or ""),
        max_chars=1200,
    )
    base_text = bt(boundary_attr(document, "text", "document_text_field_failed"))
    metadata = {
        **metadata_mapping(boundary_attr(document, "metadata", "metadata_field_failed")),
        "rank": index,
        "search_query": query,
        "search_title": title,
        "search_snippet": snippet,
    }
    if fetch_fallback:
        metadata["fetch_fallback"] = True
    merged = document.model_copy(
        update={
            "title": title,
            "text": _search_hit_context(base_text, title, snippet),
            "metadata": metadata,
        }
    )
    return sanitize_context_document(merged)


def _search_hit_context(text: str, title: str, snippet: str) -> str:
    parts = [
        text,
        f"Search result title: {title}" if title else "",
        f"Search result snippet: {snippet}" if snippet else "",
    ]
    return "\n".join(part for part in parts if part)


def _extract_with_trafilatura(raw: str) -> str:
    try:
        trafilatura: Any = importlib.import_module("trafilatura")
    except ImportError:
        return ""
    extracted = trafilatura.extract(raw, include_comments=False, include_tables=False)
    return bt(extracted or "")


def _extract_with_bs4(raw: str) -> tuple[str, str]:
    try:
        bs4: Any = importlib.import_module("bs4")
    except ImportError:
        return "", ""
    soup = bs4.BeautifulSoup(raw, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    title = sanitize_untrusted_text(soup.title.get_text(" ") if soup.title else "", max_chars=200)
    text = sanitize_untrusted_text(soup.get_text(" "))
    return title, text


def _extract_title(raw: str) -> str:
    parser = _TextExtractor()
    parser.feed(raw)
    return parser.title
