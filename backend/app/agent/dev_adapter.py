"""Deterministic fallback adapter around real Bluesky fetch.

This module exists so the frontend, API, trace, and citation contracts can run
end to end when full retrieval or provider-backed generation is unavailable.
"""

from __future__ import annotations

from time import perf_counter
from typing import Protocol

from app.schemas.api import Bullet, ExplainRequest, ExplainResponse, PostSummary, Source, Trace
from app.schemas.domain import PostContext


class BlueskyContextFetcher(Protocol):
    """Subset needed from the real Bluesky client."""

    def fetch_context(self, url: str) -> PostContext:
        """Fetch and normalize a Bluesky post context."""


class Gate3Explainer:
    """Real Bluesky fetch plus trace-marked deterministic fallback explanation."""

    def __init__(self, bluesky_client: BlueskyContextFetcher) -> None:
        self._bluesky_client = bluesky_client

    def explain(self, request: ExplainRequest) -> ExplainResponse:
        started = perf_counter()
        context = self._bluesky_client.fetch_context(request.post_url)
        sources = _sources_from_context(context)
        source_ids = [source.id for source in sources] or ["S1"]
        bullets = _bullets_from_context(context, source_ids)
        latency_ms = int((perf_counter() - started) * 1000)

        return ExplainResponse(
            post=PostSummary(
                url=context.url,
                author=context.author,
                text=context.text,
                created_at=context.created_at,
            ),
            bullets=bullets,
            sources=sources,
            trace=Trace(
                category="thread_context_fallback",
                queries=[],
                warnings=[
                    "real_bluesky_fetch_enabled",
                    "search_rag_uses_deterministic_fallback_adapter",
                    "dspy_uses_deterministic_fallback_adapter",
                ],
                latency_ms=latency_ms,
                trust_score=0.35,
                fallback_mode="safe_summary",
                guardrail_flags=[
                    "deterministic_fallback_search_rag",
                    "deterministic_fallback_dspy",
                    "limited_context_fallback",
                ],
                adapter_mode="deterministic_fallback",
                adapter_notes=[
                    "Real Bluesky post/thread fetch is active.",
                    "External retrieval or provider-backed synthesis was "
                    "unavailable for this response.",
                    "The deterministic fallback is limited to fetched Bluesky context.",
                ],
            ),
        )


def _sources_from_context(context: PostContext) -> list[Source]:
    sources = [
        Source(
            id="S1",
            title=f"Bluesky post by {context.author}",
            url=context.url,
            type="thread",
            snippet=_snippet(context.text),
        )
    ]
    for index, parent_text in enumerate(context.parent_texts, start=2):
        sources.append(
            Source(
                id=f"S{index}",
                title="Bluesky parent context",
                url=context.url,
                type="thread",
                snippet=_snippet(parent_text),
            )
        )
    return sources


def _bullets_from_context(context: PostContext, source_ids: list[str]) -> list[Bullet]:
    text = _snippet(context.text) or "The fetched post has no text in the normalized record."
    context_parts = [
        f"{len(context.parent_texts)} parent item(s)",
        f"{len(context.quoted_texts)} quoted item(s)",
        f"{len(context.links)} link(s)",
        f"{len(context.images)} image(s)",
    ]
    return [
        Bullet(
            text=f"The real Bluesky fetch found a post by {context.author}: {text}",
            source_ids=["S1"],
        ),
        Bullet(
            text="Available fetched context includes " + ", ".join(context_parts) + ".",
            source_ids=source_ids[: min(len(source_ids), 3)],
        ),
        Bullet(
            text=(
                "This result is a safe summary from fetched Bluesky context; "
                "external retrieval and provider-backed synthesis were unavailable."
            ),
            source_ids=["S1"],
        ),
    ]


def _snippet(text: str, limit: int = 220) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "..."
