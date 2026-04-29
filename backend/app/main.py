"""FastAPI scaffold for T0.

The full API contracts are implemented in T2. This tiny app exists so the
project can boot during scaffolding and developers have a stable dev command.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.config import get_settings


def create_app() -> FastAPI:
    """Create the FastAPI application."""

    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0")

    @app.get(f"{settings.api_prefix}/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

