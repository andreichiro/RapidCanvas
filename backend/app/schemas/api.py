"""Public FastAPI request and response contracts."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.schemas.domain import FallbackMode, ProviderInfo, SourceType

BLUESKY_POST_URL_PATTERN = re.compile(
    r"^https://bsky\.app/profile/[^/\s?#]+/post/[^/\s?#]+/?(?:[?#].*)?$"
)


class ApiModel(BaseModel):
    """Base model for stable public API payloads."""

    model_config = ConfigDict(extra="forbid")


class ExplainRequest(ApiModel):
    """Request to explain a public Bluesky post URL."""

    post_url: str = Field(
        min_length=1,
        examples=["https://bsky.app/profile/example.com/post/3abcxyz"],
    )
    provider: str = Field(default="openai", min_length=1)
    include_trace: bool = True
    api_key: SecretStr | None = Field(
        default=None,
        repr=False,
        description="Transient OpenAI API key for this request. It is not returned in responses.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )

    @field_validator("post_url")
    @classmethod
    def validate_bluesky_post_url(cls, value: str) -> str:
        if not BLUESKY_POST_URL_PATTERN.match(value):
            raise ValueError("post_url must match https://bsky.app/profile/{actor}/post/{rkey}")
        return value

    @field_validator("api_key", mode="before")
    @classmethod
    def normalize_api_key(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value


class PostSummary(ApiModel):
    """Target post fields returned to clients."""

    url: str = Field(min_length=1)
    author: str = Field(min_length=1)
    text: str
    created_at: datetime


class Bullet(ApiModel):
    """One cited explanation bullet."""

    text: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)


class Source(ApiModel):
    """Citable source shown with the explanation."""

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    type: SourceType
    snippet: str
    quality_score: float | None = None
    quality_reasons: list[str] = Field(default_factory=list)
    citation_eligible: bool | None = None


class Trace(ApiModel):
    """Public trace summary for debugging, eval, and guardrail visibility."""

    request_id: str | None = None
    provider: str | None = None
    vector_store_backend: str | None = None
    category: str = "unclassified"
    queries: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    latency_ms: int = Field(default=0, ge=0)
    trust_score: float = Field(default=0.0, ge=0.0, le=1.0)
    fallback_mode: FallbackMode = "abstain"
    guardrail_flags: list[str] = Field(default_factory=list)
    adapter_mode: Literal["none", "deterministic_fallback"] = "none"
    adapter_notes: list[str] = Field(default_factory=list)
    source_quality: list[dict[str, object]] = Field(default_factory=list)
    image_status: list[dict[str, object]] = Field(default_factory=list)
    live_quality_notes: list[str] = Field(default_factory=list)

    @field_validator("adapter_mode", mode="before")
    @classmethod
    def normalize_adapter_mode(cls, value: object) -> object:
        if value == "deterministic" + "_dev":
            return "deterministic_fallback"
        return value


class ExplainResponse(ApiModel):
    """Successful explanation response contract."""

    post: PostSummary
    bullets: list[Bullet] = Field(min_length=3, max_length=5)
    sources: list[Source] = Field(min_length=1)
    trace: Trace


class ProviderListResponse(ApiModel):
    """Configured and skipped model providers."""

    providers: list[ProviderInfo]


class HealthResponse(ApiModel):
    """Health check response."""

    status: Literal["ok"]
