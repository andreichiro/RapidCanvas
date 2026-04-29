"""Public API routes for the frozen Gate 2 contract."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.config import Settings
from app.deps import get_provider_catalog
from app.schemas.api import ExplainRequest, ExplainResponse, HealthResponse, ProviderListResponse


def create_api_router(settings: Settings) -> APIRouter:
    """Create versionless API routes under the configured prefix."""

    router = APIRouter(prefix=settings.api_prefix)

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
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "code": "explain_pipeline_not_implemented",
                "message": (
                    "Gate 2 freezes the request and response contract. The real "
                    "Bluesky/search/DSPy pipeline is implemented in later gates."
                ),
                "post_url": request.post_url,
            },
        )

    return router
