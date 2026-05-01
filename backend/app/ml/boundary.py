"""Shared defensive helpers for untrusted Dev B boundary containers."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from typing import Any, cast

_NOT_SINGLE_ITEM = object()
_MAX_SAFE_LIMIT = 200


def boundary_text(value: object, failure_prefix: str = "text_coercion_failed") -> str:
    if value is None:
        return ""
    if isinstance(value, bytes | bytearray):
        return bytes(value).decode("utf-8", errors="replace")
    try:
        return str(value)
    except Exception as exc:
        return f"{failure_prefix}:{exc.__class__.__name__}"


def boundary_attr(value: object, name: str, failure_prefix: str) -> object:
    try:
        return getattr(value, name)
    except Exception as exc:
        return f"{failure_prefix}:{exc.__class__.__name__}"


def bounded_items(value: object, limit: int, failure_prefix: str) -> tuple[list[object], list[str]]:
    single_item = _single_boundary_item(value)
    if single_item is not _NOT_SINGLE_ITEM:
        return cast(tuple[list[object], list[str]], single_item)
    return _bounded_iterable_items(value, safe_limit(limit), failure_prefix)


def safe_limit(value: object) -> int:
    try:
        limit = int(cast(Any, value))
    except Exception:
        return 0
    return min(limit, _MAX_SAFE_LIMIT) if limit > 0 else 0


def _single_boundary_item(value: object) -> tuple[list[object], list[str]] | object:
    if value is None:
        return [], []
    if isinstance(value, str | bytes | bytearray | Mapping):
        return [value], []
    if not isinstance(value, Iterable):
        return [value], []
    return _NOT_SINGLE_ITEM


def _bounded_iterable_items(
    value: object,
    item_limit: int,
    failure_prefix: str,
) -> tuple[list[object], list[str]]:
    if item_limit == 0:
        return [], []
    try:
        iterator = iter(cast(Iterable[object], value))
    except Exception as exc:
        return [], [f"{failure_prefix}:{exc.__class__.__name__}"]
    return _take_bounded_items(iterator, item_limit, failure_prefix)


def _take_bounded_items(
    iterator: Iterator[object],
    item_limit: int,
    failure_prefix: str,
) -> tuple[list[object], list[str]]:
    items: list[object] = []
    warnings: list[str] = []
    for _ in range(item_limit):
        try:
            items.append(next(iterator))
        except StopIteration:
            break
        except Exception as exc:
            warnings.append(f"{failure_prefix}:{exc.__class__.__name__}")
            break
    return items, warnings
