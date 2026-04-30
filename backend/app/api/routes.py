"""Public API routes for the Gate 3 vertical slice."""

from __future__ import annotations

from typing import Protocol

from fastapi import APIRouter, HTTPException, status

from app.clients.bsky import BlueskyClientError, InvalidBlueskyPostUrlError
from app.config import Settings
from app.deps import build_gate3_explainer, get_provider_catalog
from app.schemas.api import ExplainRequest, ExplainResponse, HealthResponse, ProviderListResponse


class ExplainerService(Protocol):
    """Service boundary for current and future explain implementations."""

    def explain(self, request: ExplainRequest) -> ExplainResponse:
        """Return a schema-valid explanation response."""


def create_api_router(settings: Settings, explainer: ExplainerService | None = None) -> APIRouter:
    """Create versionless API routes under the configured prefix."""

    router = APIRouter(prefix=settings.api_prefix)
    explain_service = explainer or build_gate3_explainer()

    @router.get("/health", response_model=HealthResponse, tags=["health"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @router.get("/providers", response_model=ProviderListResponse, tags=["providers"])
    def providers() -> ProviderListResponse:
        return ProviderListResponse(providers=get_provider_catalog(settings))

    @router.post(
        "/explain",
        response_model=ExplainResponse,
        status_code=status.HTTP_200_OK,
        tags=["explain"],
    )
    def explain(request: ExplainRequest) -> ExplainResponse:
        try:
            return explain_service.explain(request)
        except InvalidBlueskyPostUrlError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_bluesky_url", "message": str(exc)},
            ) from exc
        except BlueskyClientError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "bluesky_fetch_failed", "message": str(exc)},
            ) from exc

    return router
