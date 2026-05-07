from __future__ import annotations

import html
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final, cast

from app.guardrails.identifiers import safe_identifier
from app.ml.boundary import boundary_attr as ba
from app.ml.boundary import boundary_text, bounded_items
from app.schemas.domain import ContextDocument, SourceType

UNTRUSTED_LABEL_BY_SOURCE_TYPE: Final[dict[str, str]] = {
    "thread": "UNTRUSTED_THREAD_CONTEXT",
    "bluesky": "UNTRUSTED_POST_TEXT",
    "web": "UNTRUSTED_WEB_CONTEXT",
    "image": "UNTRUSTED_IMAGE_ALT_TEXT",
}

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_INVISIBLE_CHARS_RE = re.compile(r"[\u200b-\u200f\ufeff]")
_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1>",
    flags=re.IGNORECASE | re.DOTALL,
)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", flags=re.DOTALL)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_INTERNAL_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "prompt_injection_risk_score",
        "prompt_injection_flags",
        "prompt_injection_reasons",
        "sanitized",
        "untrusted_label",
    }
)
_NOT_METADATA_SCALAR: Final = object()


@dataclass(frozen=True)
class PromptInjectionPattern:
    flag: str
    pattern: re.Pattern[str]
    reason: str
    weight: float = 0.25


@dataclass(frozen=True)
class PromptInjectionScanResult:
    """Structured scan result that can be copied into trace metadata."""

    risk_score: float
    flags: tuple[str, ...]
    reasons: tuple[str, ...]
    label: str

    @property
    def is_risky(self) -> bool:
        return bool(self.flags)

    def as_metadata(self) -> dict[str, object]:
        return {
            "prompt_injection_risk_score": self.risk_score,
            "prompt_injection_flags": list(self.flags),
            "prompt_injection_reasons": list(self.reasons),
            "untrusted_label": self.label,
        }


DEFAULT_PATTERNS: Final[tuple[PromptInjectionPattern, ...]] = (
    PromptInjectionPattern(
        flag="ignore_previous_instructions",
        pattern=re.compile(
            r"\bignore\s+(?:all\s+)?(?:(previous|prior|above)\s+)?instructions\b",
            re.I,
        ),
        reason="content asks the model to ignore higher-priority instructions",
        weight=0.35,
    ),
    PromptInjectionPattern(
        flag="system_prompt_reference",
        pattern=re.compile(r"\b(system\s+prompt|system\s+message)\b", re.I),
        reason="content references hidden system prompts",
    ),
    PromptInjectionPattern(
        flag="developer_message_reference",
        pattern=re.compile(r"\b(developer\s+message|developer\s+instructions?)\b", re.I),
        reason="content references hidden developer instructions",
    ),
    PromptInjectionPattern(
        flag="secret_exfiltration",
        pattern=re.compile(
            r"\b(exfiltrate|send|reveal|print|dump)\b.{0,40}"
            r"\b(secret|token|api\s*key|key)\b",
            re.I,
        ),
        reason="content asks for secrets or API keys",
        weight=0.35,
    ),
    PromptInjectionPattern(
        flag="api_key_request",
        pattern=re.compile(
            r"\b(api\s*key|OPENAI_API_KEY|ANTHROPIC_API_KEY|GEMINI_API_KEY)\b",
            re.I,
        ),
        reason="content mentions API keys or provider secrets",
    ),
    PromptInjectionPattern(
        flag="disable_citations",
        pattern=re.compile(
            r"\b(do\s+not|don't|disable|skip|omit)\s+(cite|citations?|sources?)\b",
            re.I,
        ),
        reason="content tries to override citation requirements",
        weight=0.35,
    ),
    PromptInjectionPattern(
        flag="tool_call_instruction",
        pattern=re.compile(
            r"\b(tool\s*call|call\s+the\s+tool|invoke\s+tool|function\s*call)\b",
            re.I,
        ),
        reason="content tries to direct tool use",
    ),
    PromptInjectionPattern(
        flag="write_endpoint_instruction",
        pattern=re.compile(r"\b(POST|DELETE|PATCH|PUT)\s+(to\s+)?https?://", re.I),
        reason="content requests write-capable network behavior",
        weight=0.35,
    ),
    PromptInjectionPattern(
        flag="destructive_instruction",
        pattern=re.compile(
            r"\b(delete|remove|overwrite|reset|drop)\b.{0,40}"
            r"\b(file|repo|database|record|post)\b",
            re.I,
        ),
        reason="content contains destructive operation instructions",
    ),
)


class PromptInjectionScanner:
    def __init__(
        self,
        patterns: tuple[PromptInjectionPattern, ...] = DEFAULT_PATTERNS,
    ) -> None:
        self._patterns = patterns

    def scan(self, text: str, label: str = "UNTRUSTED_CONTEXT") -> PromptInjectionScanResult:
        flags: list[str] = []
        reasons: list[str] = []
        risk_score = 0.0
        for pattern in self._patterns:
            if pattern.pattern.search(text):
                flags.append(pattern.flag)
                reasons.append(pattern.reason)
                risk_score += pattern.weight
        return PromptInjectionScanResult(
            risk_score=min(1.0, risk_score),
            flags=tuple(dict.fromkeys(flags)),
            reasons=tuple(dict.fromkeys(reasons)),
            label=label,
        )


def sanitize_untrusted_text(text: str, max_chars: int = 6000) -> str:
    without_scripts = _SCRIPT_STYLE_RE.sub(" ", text)
    without_comments = _HTML_COMMENT_RE.sub(" ", without_scripts)
    without_tags = _HTML_TAG_RE.sub(" ", without_comments)
    decoded = html.unescape(without_tags)
    visible = _INVISIBLE_CHARS_RE.sub("", _CONTROL_CHARS_RE.sub(" ", decoded))
    compact = _WHITESPACE_RE.sub(" ", visible).strip()
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - len(" [truncated]")].rstrip() + " [truncated]"


def sanitize_context_document(
    document: ContextDocument,
    scanner: PromptInjectionScanner | None = None,
    max_chars: int = 6000,
) -> tuple[ContextDocument, PromptInjectionScanResult]:
    active_scanner = scanner or PromptInjectionScanner()
    source_type = _coerce_source_type(ba(document, "source_type", "source_type_field_failed"))
    sanitized_id = safe_identifier(ba(document, "id", "document_id_field_failed"), prefix="DOC")
    url_text = _coerce_text(ba(document, "url", "document_url_field_failed"))
    sanitized_url = sanitize_untrusted_text(url_text, max_chars=1200) or "about:blank"
    sanitized_title = (
        sanitize_untrusted_text(
            _coerce_text(ba(document, "title", "document_title_field_failed")),
            max_chars=200,
        )
        or "Untitled source"
    )
    sanitized_text = sanitize_untrusted_text(
        _coerce_text(ba(document, "text", "document_text_field_failed")),
        max_chars=max_chars,
    )
    metadata = _sanitize_metadata(ba(document, "metadata", "metadata_field_failed"))
    sanitized_metadata = dict(metadata) if isinstance(metadata, Mapping) else {"metadata": metadata}
    label = _context_label(source_type, sanitized_metadata)
    metadata_scan_text = "\n".join(_metadata_scan_parts(sanitized_metadata))
    scan_input = "\n".join(
        part for part in (sanitized_title, sanitized_text, metadata_scan_text) if part
    )
    scan = active_scanner.scan(scan_input, label=label)
    scan = _merge_upstream_scan_metadata(sanitized_metadata, scan, label=label)
    metadata = {
        **sanitized_metadata,
        "sanitized": True,
        **scan.as_metadata(),
    }
    sanitized_document = document.model_copy(
        update={
            "id": sanitized_id,
            "source_type": source_type,
            "title": sanitized_title,
            "url": sanitized_url,
            "text": sanitized_text,
            "metadata": metadata,
        }
    )
    return sanitized_document, scan


def _merge_upstream_scan_metadata(
    metadata: Mapping[str, object],
    scan: PromptInjectionScanResult,
    *,
    label: str,
) -> PromptInjectionScanResult:
    upstream_flags = _metadata_strings(metadata.get("prompt_injection_flags"))
    upstream_reasons = _metadata_strings(metadata.get("prompt_injection_reasons"))
    upstream_score = _metadata_float(metadata.get("prompt_injection_risk_score"))
    return PromptInjectionScanResult(
        risk_score=max(scan.risk_score, upstream_score),
        flags=tuple(dict.fromkeys([*upstream_flags, *scan.flags])),
        reasons=tuple(dict.fromkeys([*upstream_reasons, *scan.reasons])),
        label=label,
    )


def _metadata_strings(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, Iterable) and not isinstance(value, bytes | bytearray):
        return [
            text
            for item in value
            if (text := sanitize_untrusted_text(boundary_text(item), max_chars=200))
        ]
    text = sanitize_untrusted_text(boundary_text(value), max_chars=200)
    return [text] if text else []


def _metadata_float(value: object) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    try:
        number = float(value)  # type: ignore[arg-type]
    except Exception:
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return max(0.0, min(1.0, number))


def _sanitize_metadata(value: object, *, depth: int = 0) -> object:
    scalar = _sanitize_metadata_scalar(value)
    if scalar is not _NOT_METADATA_SCALAR:
        return scalar
    if depth >= 4:
        return sanitize_untrusted_text(boundary_text(value), max_chars=1200)
    if isinstance(value, Mapping):
        return _sanitize_mapping_metadata(value, depth=depth)
    if isinstance(value, Iterable):
        return _sanitize_iterable_metadata(value, depth=depth)
    return sanitize_untrusted_text(boundary_text(value), max_chars=1200)


def _context_label(source_type: SourceType, metadata: Mapping[str, object]) -> str:
    if source_type == "image" and metadata.get("role") == "image_description":
        return "UNTRUSTED_IMAGE_DESCRIPTION"
    return UNTRUSTED_LABEL_BY_SOURCE_TYPE[source_type]


def _sanitize_mapping_metadata(value: Mapping[object, object], *, depth: int) -> dict[str, object]:
    try:
        mapping_items = value.items()
    except Exception as exc:
        return {"metadata_iter_failed": f"metadata_iter_failed:{exc.__class__.__name__}"}
    items, warnings = bounded_items(mapping_items, 50, "metadata_iter_failed")
    sanitized: dict[str, object] = {}
    for pair in items:
        if not isinstance(pair, tuple) or len(pair) != 2:
            continue
        key, item = pair
        key_text = sanitize_untrusted_text(boundary_text(key), max_chars=120) or "metadata_key"
        sanitized[key_text] = _sanitize_metadata(item, depth=depth + 1)
    return {**sanitized, **({"metadata_iter_failed": warnings} if warnings else {})}


def _sanitize_iterable_metadata(value: Iterable[object], *, depth: int) -> list[object]:
    items, warnings = bounded_items(value, 50, "metadata_iter_failed")
    return [*(_sanitize_metadata(item, depth=depth + 1) for item in items), *warnings]


def _sanitize_metadata_scalar(value: object) -> object:
    if isinstance(value, str):
        return sanitize_untrusted_text(value, max_chars=1200)
    if isinstance(value, bytes | bytearray):
        return sanitize_untrusted_text(_coerce_text(value), max_chars=1200)
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return _NOT_METADATA_SCALAR


def _coerce_text(value: object) -> str:
    return boundary_text(value)


def _coerce_source_type(value: object) -> SourceType:
    text = boundary_text(value, "source_type_text_failed")
    if text in UNTRUSTED_LABEL_BY_SOURCE_TYPE:
        return cast(SourceType, text)
    return "web"


def _metadata_scan_parts(value: object) -> Iterable[str]:
    if isinstance(value, str):
        if value:
            yield value
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = boundary_text(key)
            if key_text in _INTERNAL_METADATA_KEYS:
                continue
            yield key_text
            yield from _metadata_scan_parts(item)
        return
    if isinstance(value, Iterable) and not isinstance(value, bytes | bytearray):
        for item in value:
            yield from _metadata_scan_parts(item)


def sanitize_context_documents(
    documents: list[ContextDocument],
    scanner: PromptInjectionScanner | None = None,
    max_chars: int = 6000,
) -> tuple[list[ContextDocument], list[PromptInjectionScanResult]]:
    sanitized: list[ContextDocument] = []
    scans: list[PromptInjectionScanResult] = []
    active_scanner = scanner or PromptInjectionScanner()
    for document in documents:
        clean_document, scan = sanitize_context_document(
            document,
            scanner=active_scanner,
            max_chars=max_chars,
        )
        sanitized.append(clean_document)
        scans.append(scan)
    return sanitized, scans
