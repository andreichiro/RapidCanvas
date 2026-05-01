"""Shared guardrail policy constants for the Dev C agent lane."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

UNTRUSTED_CONTENT_LABELS: tuple[str, ...] = (
    "UNTRUSTED_POST_TEXT",
    "UNTRUSTED_THREAD_CONTEXT",
    "UNTRUSTED_WEB_CONTEXT",
    "UNTRUSTED_IMAGE_ALT_TEXT",
    "UNTRUSTED_IMAGE_DESCRIPTION",
)

_PROMPT_INJECTION_PATTERNS: tuple[str, ...] = (
    r"\bignore\s+(all\s+)?(previous|prior|above)\s+instructions\b",
    r"\bignore\s+all\s+instructions\b",
    r"\bsystem\s+prompt\b",
    r"\bdeveloper\s+message\b",
    r"\bexfiltrate\b",
    r"\bsend\s+(the\s+)?(api\s+)?key\b",
    r"\bapi\s*key\b",
    r"\bdo\s+not\s+cite\b",
    r"\bdisable\s+citations?\b",
    r"\btool\s+call\b",
    r"\bpost\s+to\b",
    r"\bdelete\b",
)

_FORBIDDEN_OUTPUT_PATTERNS: tuple[str, ...] = (
    r"\bsystem\s+prompt\b",
    r"\bdeveloper\s+message\b",
    r"\bapi\s*key\b",
    r"\bsk-[A-Za-z0-9_-]{12,}\b",
    r"\bignore\s+(all\s+)?(previous|prior|above)\s+instructions\b",
    r"\bignore\s+all\s+instructions\b",
    r"\bdo\s+not\s+cite\b",
    r"\bdisable\s+citations?\b",
    r"\breveal\s+(the\s+)?(hidden\s+)?instructions\b",
)


@dataclass(frozen=True)
class GuardrailPolicy:
    """Versioned thresholds and patterns used by output and trust guardrails."""

    version: str = "gate4-dev-c-v1"
    min_bullets: int = 3
    max_bullets: int = 5
    min_normal_trust: float = 0.62
    min_partial_trust: float = 0.42
    max_source_text_chars: int = 4000
    prompt_injection_patterns: tuple[str, ...] = field(
        default_factory=lambda: _PROMPT_INJECTION_PATTERNS
    )
    forbidden_output_patterns: tuple[str, ...] = field(
        default_factory=lambda: _FORBIDDEN_OUTPUT_PATTERNS
    )

    def prompt_injection_hits(self, text: str) -> list[str]:
        """Return detector pattern names found in untrusted content."""

        return _pattern_hits(self.prompt_injection_patterns, text)

    def forbidden_output_hits(self, text: str) -> list[str]:
        """Return forbidden-output pattern names found in generated text."""

        return _pattern_hits(self.forbidden_output_patterns, text)


DEFAULT_POLICY = GuardrailPolicy()


def compact_text(text: str, limit: int = 260) -> str:
    """Collapse whitespace and cap text without preserving prompt payloads."""

    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "..."


def _pattern_hits(patterns: tuple[str, ...], text: str) -> list[str]:
    hits: list[str] = []
    for pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            hits.append(_pattern_name(pattern))
    return hits


def _pattern_name(pattern: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", pattern.lower()).strip("_")
    return cleaned[:64] or "pattern"
