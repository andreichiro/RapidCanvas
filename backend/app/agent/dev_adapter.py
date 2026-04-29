"""Gate 3 deterministic adapter around real Bluesky fetch.

This module is intentionally not the final Search/RAG/DSPy implementation. It
exists so the frontend, API, trace, and citation contracts can run end to end
while later gates replace the adapter with real retrieval and DSPy modules.
"""

from __future__ import annotations

from time import perf_counter
from typing import Protocol

from app.clients.bsky import BlueskyClient
from app.schemas.api import Bullet, ExplainRequest, ExplainResponse, PostSummary, Source, Trace
from app.schemas.domain import PostContext


class BlueskyContextFetcher(Protocol):
    """Subset needed from the real Bluesky client."""

    def fetch_context(self, url: str) -> PostContext:
        """Fetch and normalize a Bluesky post context."""


class Gate3Explainer:
    """Real Bluesky fetch plus trace-marked deterministic dev explanation."""

    def __init__(self, bluesky_client: BlueskyContextFetcher | None = None) -> None:
        self._bluesky_client = bluesky_client or BlueskyClient()

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
                category="gate3_vertical_slice",
                queries=[],
                warnings=[
                    "real_bluesky_fetch_enabled",
                    "search_rag_uses_deterministic_dev_adapter",
                    "dspy_uses_deterministic_dev_adapter",
                ],
                latency_ms=latency_ms,
                trust_score=0.35,
                fallback_mode="safe_summary",
                guardrail_flags=[
                    "dev_adapter_search_rag",
                    "dev_adapter_dspy",
                    "not_final_explanation",
                ],
                adapter_mode="deterministic_dev",
                adapter_notes=[
                    "Real Bluesky post/thread fetch is active.",
                    "Search/RAG and DSPy are deterministic dev adapters for Gate 3 only.",
                    "This response cannot satisfy final Search/RAG, DSPy, eval, or citation rows.",
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
                "This Gate 3 result is a safe summary from fetched Bluesky context; "
                "broader Search/RAG and DSPy synthesis are not final yet."
            ),
            source_ids=["S1"],
        ),
    ]


def _snippet(text: str, limit: int = 220) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "..."
