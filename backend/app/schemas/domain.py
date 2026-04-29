"""Internal domain contracts shared by API, agent, retrieval, and eval lanes."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SourceType = Literal["thread", "bluesky", "web", "image"]
FallbackMode = Literal["none", "partial", "abstain", "safe_summary"]


class DomainModel(BaseModel):
    """Base model with stable JSON behavior for cross-lane contracts."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class PostRef(DomainModel):
    """Normalized reference for a Bluesky feed post."""

    actor: str = Field(min_length=1)
    rkey: str = Field(min_length=1)
    did: str | None = None
    at_uri: str = Field(min_length=1)


class ImageRef(DomainModel):
    """Image reference extracted from a post embed."""

    url: str = Field(min_length=1)
    alt_text: str | None = None


class PostContext(DomainModel):
    """Normalized Bluesky post context before retrieval and explanation."""

    url: str = Field(min_length=1)
    at_uri: str = Field(min_length=1)
    author: str = Field(min_length=1)
    text: str
    created_at: datetime
    parent_texts: list[str] = Field(default_factory=list)
    quoted_texts: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    images: list[ImageRef] = Field(default_factory=list)


class ContextDocument(DomainModel):
    """Search, thread, web, or image text available as untrusted evidence."""

    id: str = Field(min_length=1)
    source_type: SourceType
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Evidence(DomainModel):
    """A retrieved evidence chunk tied back to a source document."""

    id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    score: float = Field(ge=0.0)
    source_id: str = Field(min_length=1)


class TraceEvent(DomainModel):
    """Per-step diagnostic event for later agent and evaluation traces."""

    step: str = Field(min_length=1)
    status: str = Field(min_length=1)
    tool: str | None = None
    latency_ms: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)


class TrustAssessment(DomainModel):
    """Trust and fallback decision used by API responses and eval reports."""

    score: float = Field(ge=0.0, le=1.0)
    fallback_mode: FallbackMode
    flags: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class ProviderInfo(DomainModel):
    """Public provider availability contract."""

    name: str = Field(min_length=1)
    configured: bool
    skipped_reason: str | None = None
    default_model: str | None = None
