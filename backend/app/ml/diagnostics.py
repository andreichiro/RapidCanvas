"""Retrieval diagnostics surfaced for agent trace and guardrails."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.guardrails.prompt_injection import PromptInjectionScanResult
from app.schemas.domain import ContextDocument


@dataclass(frozen=True)
class RetrievalDiagnostics:
    """Warnings and guardrail flags surfaced by a retrieval pass."""

    prompt_injection_flags: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def retrieval_diagnostics(
    documents: list[ContextDocument],
    scans: Sequence[PromptInjectionScanResult],
) -> RetrievalDiagnostics:
    """Build trace-ready retrieval diagnostics from prompt-injection scans."""

    flags: list[str] = []
    warnings: list[str] = []
    for document, scan in zip(documents, scans, strict=True):
        for flag in scan.flags:
            flags.append(flag)
            warnings.append(f"prompt_injection_risk:{document.id}:{flag}")
    return RetrievalDiagnostics(
        prompt_injection_flags=tuple(dict.fromkeys(flags)),
        warnings=tuple(dict.fromkeys(warnings)),
    )
