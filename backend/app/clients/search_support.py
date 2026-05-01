"""Internal helpers for search provider normalization and diagnostics."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextvars import ContextVar
from threading import local
from typing import Any, overload

from app.clients.extraction import Resolver, redact_url_for_warning, validate_source_url_metadata
from app.ml.boundary import boundary_attr, boundary_text, bounded_items
from app.schemas.domain import ContextDocument

_MAX_WARNING_ITEMS = 50


class WarningState(Sequence[str]):
    def __init__(self) -> None:
        self._last: list[str] = []
        self._context: ContextVar[list[str] | None] = ContextVar(
            f"search_warnings:{id(self)}",
            default=None,
        )
        self._thread = local()

    def set(self, warnings: Iterable[object]) -> None:
        values = warning_strings(warnings)
        self._last = values
        self._context.set(values)
        self._thread.warnings = values

    def get(self) -> list[str]:
        values = self._context.get()
        if values is None:
            values = getattr(self._thread, "warnings", None)
        return list(values or self._last)

    def __iter__(self) -> Iterator[str]:
        return iter(self.get())

    def __len__(self) -> int:
        return len(self.get())

    @overload
    def __getitem__(self, index: int) -> str: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[str]: ...

    def __getitem__(self, index: int | slice) -> str | Sequence[str]:
        return self.get()[index]

    def __contains__(self, item: object) -> bool:
        return item in self.get()

    def __bool__(self) -> bool:
        return bool(self.get())

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str | bytes | bytearray):
            return False
        if isinstance(other, WarningState):
            return self.get() == other.get()
        if isinstance(other, Sequence):
            try:
                return self.get() == list(other)
            except Exception:
                return False
        return False

    def __repr__(self) -> str:
        return repr(self.get())


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def items(value: Any) -> Iterable[Any]:
    return value if isinstance(value, list | tuple) else []


def get_value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def provider_failure_warning(provider: object, exc: Exception) -> str:
    return f"search_provider_failed:{provider.__class__.__name__}:{exc.__class__.__name__}"


def warning_strings(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str | bytes | bytearray):
        return [_warning_text(value)]
    if isinstance(value, Mapping):
        return [boundary_text(value, "warning_text_failed")]
    if isinstance(value, Iterable):
        warnings, iter_warnings = bounded_items(value, _MAX_WARNING_ITEMS, "warning_iter_failed")
        return [*(_warning_text(warning) for warning in warnings), *iter_warnings]
    return [boundary_text(value, "warning_text_failed")]


def _warning_text(value: object) -> str:
    return boundary_text(value, "warning_text_failed")


def blocked_document_url_warnings(
    document: ContextDocument,
    *,
    resolver: Resolver | None = None,
) -> tuple[str, ...]:
    allow_at_uri = boundary_text(
        boundary_attr(document, "source_type", "source_type_field_failed"),
        "source_type_text_failed",
    ) in {
        "bluesky",
        "thread",
    }
    safety = validate_source_url_metadata(
        boundary_attr(document, "url", "document_url_field_failed"),
        allow_at_uri=allow_at_uri,
        resolver=resolver,
    )
    return safety.warnings if not safety.allowed else ()


def blocked_url_warning(url: object, url_warnings: tuple[str, ...]) -> str:
    return f"blocked_url:{redact_url_for_warning(url)}:{'|'.join(url_warnings)}"


def post_text(post: Any) -> str:
    record = get_value(post, "record", {})
    return boundary_text(get_value(record, "text", "") or get_value(post, "text", "") or "")


def author_handle(post: Any) -> str:
    author = get_value(post, "author", {})
    return boundary_text(get_value(author, "handle", None) or get_value(author, "did", "unknown"))


def post_url(post: Any, fallback_uri: str) -> str:
    author = author_handle(post)
    uri = fallback_uri or boundary_text(get_value(post, "uri", ""))
    rkey = uri.rsplit("/", maxsplit=1)[-1] if "/" in uri else ""
    if author != "unknown" and rkey:
        return f"https://bsky.app/profile/{author}/post/{rkey}"
    return uri or "https://bsky.app"
