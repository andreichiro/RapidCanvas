"""Prompt-injection scanning and sanitization for untrusted evidence.

All post, thread, web, and image text is treated as data. This module keeps the
retrieval lane honest by removing executable-looking page noise, normalizing
control characters, and flagging text that tries to override the system's tool,
secret, or citation policy.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Final

from app.schemas.domain import ContextDocument, SourceType

UNTRUSTED_LABEL_BY_SOURCE_TYPE: Final[dict[SourceType, str]] = {
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


@dataclass(frozen=True)
class PromptInjectionPattern:
    """One heuristic prompt-injection pattern."""

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
        """Return whether any injection-like content was found."""

        return bool(self.flags)

    def as_metadata(self) -> dict[str, object]:
        """Serialize the scan result for document metadata or trace payloads."""

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
    """Fast deterministic scanner for obvious prompt-injection attempts."""

    def __init__(
        self,
        patterns: tuple[PromptInjectionPattern, ...] = DEFAULT_PATTERNS,
    ) -> None:
        self._patterns = patterns

    def scan(self, text: str, label: str = "UNTRUSTED_CONTEXT") -> PromptInjectionScanResult:
        """Scan untrusted text and return flags without executing or interpreting it."""

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
    """Normalize untrusted text while preserving useful evidence content."""

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
    """Return a sanitized copy of a document plus its prompt-injection scan."""

    active_scanner = scanner or PromptInjectionScanner()
    label = UNTRUSTED_LABEL_BY_SOURCE_TYPE.get(document.source_type, "UNTRUSTED_CONTEXT")
    sanitized_text = sanitize_untrusted_text(document.text, max_chars=max_chars)
    scan = active_scanner.scan(sanitized_text, label=label)
    metadata = {
        **document.metadata,
        "sanitized": True,
        **scan.as_metadata(),
    }
    sanitized_document = document.model_copy(
        update={"text": sanitized_text, "metadata": metadata}
    )
    return sanitized_document, scan


def sanitize_context_documents(
    documents: list[ContextDocument],
    scanner: PromptInjectionScanner | None = None,
    max_chars: int = 6000,
) -> tuple[list[ContextDocument], list[PromptInjectionScanResult]]:
    """Sanitize a batch of documents and collect injection scan results."""

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
