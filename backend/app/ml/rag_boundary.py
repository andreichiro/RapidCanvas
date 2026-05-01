"""Defensive RAG component diagnostics normalization."""

from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar
from threading import local
from typing import cast

from app.ml.c2_policy import diagnostic_strings
from app.ml.diagnostics import RetrievalDiagnostics


class RetrievalDiagnosticsState:
    def __init__(self) -> None:
        self._last = RetrievalDiagnostics()
        self._context: ContextVar[RetrievalDiagnostics | None] = ContextVar(
            f"rag_diagnostics:{id(self)}",
            default=None,
        )
        self._thread = local()

    def set(self, diagnostics: RetrievalDiagnostics) -> None:
        self._last = diagnostics
        self._context.set(diagnostics)
        self._thread.diagnostics = diagnostics

    def get(self) -> RetrievalDiagnostics:
        context_diagnostics = self._context.get()
        if context_diagnostics is not None:
            return context_diagnostics
        thread_diagnostics = getattr(self._thread, "diagnostics", None)
        return thread_diagnostics or self._last


def safe_last_diagnostics(rag_service: object) -> tuple[RetrievalDiagnostics, list[str]]:
    try:
        diagnostics = getattr(rag_service, "last_diagnostics", RetrievalDiagnostics())
        flags = diagnostic_strings(getattr(diagnostics, "prompt_injection_flags", ()))
        warnings = diagnostic_strings(getattr(diagnostics, "warnings", ()))
        reranker_scores = getattr(diagnostics, "reranker_scores", {})
    except Exception as exc:
        return RetrievalDiagnostics(), [f"retrieval_diagnostics_failed:{exc.__class__.__name__}"]
    return RetrievalDiagnostics(
        prompt_injection_flags=tuple(flags),
        warnings=tuple(warnings),
        reranker_scores=cast(dict[str, float], reranker_scores)
        if isinstance(reranker_scores, Mapping)
        else {},
    ), []
