"""FastAPI application for the Bluesky Contextual Post Explainer."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.rate_limit import ExplainRateLimitMiddleware
from app.api.request_context import RequestContextMiddleware, configure_request_logging
from app.api.routes import ExplainerService, create_api_router
from app.config import get_settings


def create_app(explainer: ExplainerService | None = None) -> FastAPI:
    """Create the FastAPI application."""

    configure_request_logging()
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0")
    if settings.enable_rate_limiting:
        app.add_middleware(
            ExplainRateLimitMiddleware,
            api_prefix=settings.api_prefix,
            max_requests=settings.rate_limit_max_explain_requests,
            window_seconds=settings.rate_limit_window_seconds,
            trusted_proxy_hosts=settings.trusted_proxy_hosts,
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
    )
    app.add_middleware(
        RequestContextMiddleware,
        trusted_proxy_hosts=settings.trusted_proxy_hosts,
    )
    app.include_router(create_api_router(settings, explainer=explainer))

    return app


app = create_app()
