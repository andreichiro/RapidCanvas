"""Public API routes for the current Bluesky explainer contract."""

from __future__ import annotations

import re
from typing import Protocol

from fastapi import APIRouter, HTTPException, status

from app.clients.bsky import BlueskyClientError, InvalidBlueskyPostUrlError
from app.config import Settings
from app.deps import build_current_explainer, get_provider_catalog
from app.schemas.api import ExplainRequest, ExplainResponse, HealthResponse, ProviderListResponse

_SENSITIVE_ERROR_RE = re.compile(
    r"(?i)(traceback|file\s+\"|openai_api_key|anthropic_api_key|gemini_api_key|api[_-]?key|"
    r"secret|token|sk-[a-z0-9_-]{6,})"
)
_MAX_ERROR_MESSAGE_LENGTH = 240


class ExplainerService(Protocol):
    """Service boundary for current and future explain implementations."""

    def explain(self, request: ExplainRequest) -> ExplainResponse:
        """Return a schema-valid explanation response."""


class _ExplainerResolver:
    def __init__(self, settings: Settings, explainer: ExplainerService | None) -> None:
        self._settings = settings
        self._injected = explainer
        self._default = explainer

    def for_request(self, request: ExplainRequest) -> ExplainerService:
        if self._injected is not None:
            return self._injected
        if request.api_key is None and self._settings.openai_api_key is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "missing_openai_api_key",
                    "message": (
                        "OpenAI API key is required for embeddings and "
                        "provider-backed explanations."
                    ),
                },
            )
        if request.api_key is not None:
            request_settings = self._settings.model_copy(
                update={"openai_api_key": request.api_key}
            )
            return build_current_explainer(settings=request_settings)
        if self._default is None:
            self._default = build_current_explainer(settings=self._settings)
        return self._default


def create_api_router(settings: Settings, explainer: ExplainerService | None = None) -> APIRouter:
    """Create versionless API routes under the configured prefix."""

    router = APIRouter(prefix=settings.api_prefix)
    explainer_resolver = _ExplainerResolver(settings, explainer)

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
            return explainer_resolver.for_request(request).explain(request)
        except HTTPException:
            raise
        except Exception as exc:
            raise _http_error_for_explain_failure(exc) from exc

    return router


def _http_error_for_explain_failure(exc: Exception) -> HTTPException:
    if isinstance(exc, InvalidBlueskyPostUrlError):
        return HTTPException(
            status_code=422,
            detail={
                "code": "invalid_bluesky_url",
                "message": _safe_error_message(
                    str(exc),
                    fallback="Expected https://bsky.app/profile/{actor}/post/{rkey}",
                ),
            },
        )
    if isinstance(exc, BlueskyClientError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "bluesky_fetch_failed",
                "message": _safe_error_message(
                    str(exc),
                    fallback="Unable to fetch Bluesky post context.",
                ),
            },
        )
    if isinstance(exc, TimeoutError | ConnectionError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "runtime_dependency_unavailable",
                "message": _safe_error_message(
                    str(exc),
                    fallback=(
                        "A runtime dependency was unavailable while explaining "
                        "this post. Please retry shortly."
                    ),
                ),
            },
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={
            "code": "explanation_failed",
            "message": _safe_error_message(
                str(exc),
                fallback=(
                    "The explainer could not complete this request safely. "
                    "Please retry or use a different public Bluesky post."
                ),
            ),
        },
    )


def _safe_error_message(message: str, *, fallback: str) -> str:
    compact = " ".join(message.split())
    if not compact or _SENSITIVE_ERROR_RE.search(compact):
        return fallback
    return compact[:_MAX_ERROR_MESSAGE_LENGTH]
