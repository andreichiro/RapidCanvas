"""Safe identifiers for untrusted source and evidence labels."""

from __future__ import annotations

import hashlib
import re

from app.ml.boundary import boundary_text

_SAFE_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9_.:-]{1,120}")
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def safe_identifier(value: object, *, prefix: str = "ID") -> str:
    text = _identifier_text(value)
    compact = _WHITESPACE_RE.sub(" ", _TAG_RE.sub(" ", text)).strip()
    if _SAFE_IDENTIFIER_RE.fullmatch(compact):
        return compact
    digest_source = compact or text or prefix
    digest = hashlib.sha256(digest_source.encode("utf-8", errors="replace")).hexdigest()
    return f"{prefix}-{digest[:12]}"


def _identifier_text(value: object) -> str:
    return boundary_text(value, "identifier_text_failed")
