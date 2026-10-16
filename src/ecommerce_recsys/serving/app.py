"""FastAPI transport for a pinned snapshot and an explicit request contract."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from ecommerce_recsys.artifacts import load_bundle
from ecommerce_recsys.serving.boundary import RequestBoundary, error_response
from ecommerce_recsys.serving.contracts import (
    ErrorResponse,
    HealthResponse,
    RecommendationRequest,
    RecommendationResponse,
    ServiceSettings,
)
from ecommerce_recsys.serving.service import (
    Busy,
    InferenceFailed,
    NotReady,
    RecommendationService,
    State,
)


def create_app(settings: ServiceSettings | None = None, *, loader=load_bundle) -> FastAPI:
    """Create routes without loading files. ASGI lifespan owns model lifetime."""
    settings = settings or ServiceSettings.from_environment()
    service = RecommendationService(settings, loader=loader)

    @asynccontextmanager
    async def lifespan(app):
        await service.start()
        try:
            yield
        finally:
            await service.stop()

    app = FastAPI(
        title="Retailrocket recommendation API",
        version="1.0.0",
        description="Recommendations from one verified historical snapshot. User IDs select stored snapshot context; dynamic histories are not accepted.",
        lifespan=lifespan,
        responses={
            404: {"model": ErrorResponse, "description": "Unknown endpoint."},
            405: {"model": ErrorResponse, "description": "Unsupported HTTP method."},
        },
    )
    app.state.service = service
    app.add_middleware(RequestBoundary)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        fields = sorted(
            {
                str(entry["loc"][1])
                if len(entry["loc"]) > 1 and entry["loc"][1] in {"user_id", "k"}
                else "body"
                for entry in error.errors()
            }
        )
        return error_response(
            request.state.request_id,
            422,
            "validation_error",
            "Request body does not match the recommendation schema.",
            fields=fields,
        )

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return error_response(
            request.state.request_id,
            error.status_code,
            "http_error",
            "Requested endpoint or method is unavailable.",
            headers=error.headers,
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        return error_response(
            request.state.request_id, 500, "internal_error", "The request could not be completed."
        )

    @app.get("/health/live", response_model=HealthResponse)
    async def live(request: Request):
        return HealthResponse(
            request_id=request.state.request_id, status="alive", state=service.state.value
        )

    @app.get(
        "/health/ready", response_model=HealthResponse, responses={503: {"model": HealthResponse}}
    )
    async def ready(request: Request):
        healthy = service.state == State.READY
        result = HealthResponse(
            request_id=request.state.request_id,
            status="ready" if healthy else "not_ready",
            state=service.state.value,
            **(service.identity.model_dump() if healthy else {}),
        )
        return JSONResponse(
            result.model_dump(exclude_none=True), status_code=200 if healthy else 503
        )

    @app.post(
        "/v1/recommendations",
        response_model=RecommendationResponse,
        responses={status: {"model": ErrorResponse} for status in (400, 413, 415, 422, 500, 503)},
    )
    async def recommend(body: RecommendationRequest, request: Request):
        try:
            return await service.recommend(body.user_id, body.k, request.state.request_id)
        except NotReady:
            return error_response(
                request.state.request_id, 503, "not_ready", "Recommendation service is not ready."
            )
        except Busy:
            return error_response(
                request.state.request_id,
                503,
                "busy",
                "Recommendation service is busy; retry later.",
                headers={"Retry-After": "1"},
            )
        except InferenceFailed:
            return error_response(
                request.state.request_id,
                500,
                "inference_failed",
                "Recommendation execution failed; service requires restart.",
            )

    return app
