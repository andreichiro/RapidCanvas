"""FastAPI application for the Bluesky Contextual Post Explainer."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import ExplainerService, create_api_router
from app.config import get_settings


def create_app(explainer: ExplainerService | None = None) -> FastAPI:
    """Create the FastAPI application."""

    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )
    app.include_router(create_api_router(settings, explainer=explainer))

    return app


app = create_app()
