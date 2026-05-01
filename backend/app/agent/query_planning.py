"""Bounded runtime query planning helpers for one-shot Search/RAG."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Sequence
from urllib.parse import urlparse

from app.schemas.domain import PostContext

MAX_RUNTIME_QUERIES = 3
MAX_ADAPTIVE_QUERIES = 1
_SENSITIVE_TOKEN_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")


def runtime_queries(post: PostContext, category: str, planned_queries: Sequence[str]) -> list[str]:
    """Merge model-planned and post-context search hints under the Gate 7 cap."""

    planned = bounded_queries(planned_queries)
    base = planned[:1] or [_post_category_query(post, category)]
    queries = [*base, *_context_queries(post, category), *planned[1:]]
    return bounded_queries(queries) or [_safe_post_query(post)]


def adaptive_runtime_queries(
    post: PostContext,
    category: str,
    previous_queries: Sequence[str],
) -> list[str]:
    """Return one safe broader/refined query for the capped second retrieval round."""

    previous = set(bounded_queries(previous_queries))
    post_part = _compact_query_part(post.text, max_words=6)
    candidates = bounded_queries(
        [
            f"{post.author} {category} background context",
            f"{post_part} background context" if post_part else "",
            _safe_post_query(post),
        ]
    )
    return [query for query in candidates if query not in previous][:MAX_ADAPTIVE_QUERIES]


def bounded_queries(queries: Sequence[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        query_text = _sanitize_query_text(query)
        if not query_text or query_text in seen:
            continue
        seen.add(query_text)
        deduped.append(query_text)
        if len(deduped) >= MAX_RUNTIME_QUERIES:
            break
    return deduped


def _context_queries(post: PostContext, category: str) -> list[str]:
    queries: list[str] = []
    thread_part = _thread_context_part(post)
    if thread_part:
        queries.append(f"{thread_part} {category} context")
    link_part = _link_context_part(post)
    if link_part:
        post_part = _compact_query_part(post.text, max_words=8) or post.author
        queries.append(f"{post_part} {link_part} {category} context")
    return queries


def _safe_post_query(post: PostContext) -> str:
    author = post.author.strip() or "unknown-author"
    return f"{author} Bluesky post context"


def _post_category_query(post: PostContext, category: str) -> str:
    post_part = _compact_query_part(post.text, max_words=12) or post.author
    return f"{post_part} {category} context"


def _thread_context_part(post: PostContext) -> str:
    thread_texts = [
        *_first_texts(post.quoted_texts, limit=1),
        *_first_texts(post.parent_texts, limit=1),
    ]
    return _compact_query_part(" ".join(thread_texts), max_words=18)


def _link_context_part(post: PostContext) -> str:
    parts: list[str] = []
    external_link_count = 0
    for link in post.external_links:
        link_hosts = _host_parts((link.url,), limit=1)
        if not link_hosts:
            continue
        parts.extend(_first_texts((link.title, link.description), limit=2))
        parts.extend(link_hosts)
        external_link_count += 1
        if external_link_count >= 2:
            break
    parts.extend(_host_parts(post.links, limit=3))
    return _compact_query_part(" ".join(parts), max_words=14)


def _first_texts(values: Sequence[object], *, limit: int) -> list[str]:
    texts: list[str] = []
    for value in values:
        text = _compact_query_part(value, max_words=12)
        if text:
            texts.append(text)
        if len(texts) >= limit:
            break
    return texts


def _host_parts(values: Sequence[object], *, limit: int) -> list[str]:
    hosts: list[str] = []
    for value in values:
        host = _safe_host_part(value)
        if not host:
            continue
        hosts.append(host)
        if len(hosts) >= limit:
            break
    return hosts


def _safe_host_part(value: object) -> str:
    text = str(value).strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.username is not None or parsed.password is not None:
        return ""
    host = _candidate_hostname(text, parsed.hostname)
    if _blocked_query_host(host):
        return ""
    visible = parsed.netloc or parsed.path or text
    return "" if _blocked_query_text(visible) else visible


def _sanitize_query_text(value: object) -> str:
    tokens: list[str] = []
    for token in str(value).split():
        if _unsafe_query_token(token):
            continue
        tokens.append(token)
    return " ".join(tokens)[:240]


def _unsafe_query_token(token: str) -> bool:
    stripped = token.strip(".,;:()[]{}<>\"'")
    if not stripped:
        return False
    if _SENSITIVE_TOKEN_RE.search(stripped):
        return True
    if "@" in stripped.split("/", 1)[0]:
        return True
    parsed = urlparse(stripped)
    if parsed.username is not None or parsed.password is not None:
        return True
    if parsed.scheme and parsed.hostname and _blocked_query_host(parsed.hostname):
        return True
    return _looks_like_unsafe_host(stripped)


def _looks_like_unsafe_host(text: str) -> bool:
    candidate = _candidate_hostname(text, urlparse(text).hostname)
    return bool(candidate) and _blocked_query_host(candidate)


def _candidate_hostname(text: str, parsed_hostname: str | None) -> str:
    if parsed_hostname:
        return parsed_hostname
    return text.split("/", 1)[0].split("?", 1)[0].strip("[]")


def _blocked_query_host(hostname: str) -> bool:
    host = hostname.rstrip(".").lower()
    if not host:
        return False
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        return True
    if _contains_private_ip_hint(host):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return not address.is_global


def _blocked_query_text(text: str) -> bool:
    return _blocked_query_host(_candidate_hostname(text, urlparse(text).hostname))


def _contains_private_ip_hint(host: str) -> bool:
    return (
        "127.0.0.1" in host
        or "0.0.0.0" in host
        or "169.254." in host
        or "192.168." in host
        or host.startswith("10.")
        or any(host.startswith(f"172.{octet}.") for octet in range(16, 32))
    )


def _compact_query_part(value: object, *, max_words: int) -> str:
    return " ".join(str(value).split()[:max_words])[:160]
