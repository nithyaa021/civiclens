"""CivicLens AI - FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.db.indexes import ensure_indexes
from app.db.mongo import close_resources, get_database
from app.models.common import ErrorResponse

logger = get_logger("civiclens.app")

DESCRIPTION = """
**CivicLens AI** is a municipal complaint intelligence platform: citizens file
complaints, NLP + computer-vision models classify them, semantic similarity
detects duplicates, and issues are clustered by location and prioritised for
ward officers.

### Getting started
1. `POST /api/v1/auth/register` - create a citizen account.
2. `POST /api/v1/auth/login` - exchange credentials for a token pair.
3. Click **Authorize** and paste the `access_token` to call protected endpoints.

### Authentication
All protected endpoints expect `Authorization: Bearer <access_token>`.
Access tokens are short lived (default 30 min); use `POST /api/v1/auth/refresh`
with the `refresh_token` to rotate them. Refresh tokens are **single use** -
rotating revokes the previous one.

### Roles
| Role | Capabilities |
|---|---|
| `citizen` | File/view own complaints, receive notifications |
| `ward_officer` | Manage complaints in assigned wards |
| `admin` | Full access, including user administration |

### Errors
Every non-2xx response uses one envelope:
```json
{"error": {"code": "not_found", "message": "...", "details": {}}}
```
Rate-limited responses include a `Retry-After` header.
"""

OPENAPI_TAGS = [
    {
        "name": "health",
        "description": "Liveness and readiness probes used by ops tooling.",
    },
    {
        "name": "auth",
        "description": "Registration, login and refresh-token rotation.",
    },
    {
        "name": "users",
        "description": (
            "Admin-only account administration (provision officers, change roles/status)."
        ),
    },
    {
        "name": "jobs",
        "description": "Asynchronous AI/worker jobs: embeddings, image analysis, notifications.",
    },
    {
        "name": "complaints",
        "description": (
            "Filing, similarity search, workflow, upvotes, evidence photos, "
            "resolution verification and the audit trail."
        ),
    },
    {
        "name": "wards",
        "description": "Ward boundaries, sensitive sites and open-complaint counts.",
    },
    {
        "name": "clusters",
        "description": "Recurring issues: geo+semantic clusters with affected areas.",
    },
    {
        "name": "forecasts",
        "description": "14-day complaint-volume hotspot forecasts per ward and category.",
    },
    {
        "name": "assistant",
        "description": "Role-scoped natural-language questions over complaint data.",
    },
    {
        "name": "voice",
        "description": "Whisper speech-to-text for English, Hindi and Kannada reports.",
    },
    {
        "name": "media",
        "description": "Evidence photo downloads with per-role access control.",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level, json_logs=settings.json_logs)
    await ensure_indexes(get_database(settings))
    logger.info(
        "application_started",
        environment=settings.environment,
        version=settings.app_version,
        api_prefix=settings.api_v1_prefix,
    )
    yield
    await close_resources()
    logger.info("application_stopped")


def create_app() -> FastAPI:
    """Build the FastAPI application with middleware and error handlers."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=DESCRIPTION,
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        contact={"name": "CivicLens AI", "url": "https://example.org/civiclens"},
        license_info={"name": "MIT"},
        responses={
            401: {
                "model": ErrorResponse,
                "description": "Missing, expired or invalid access token.",
            },
            429: {
                "model": ErrorResponse,
                "description": "Rate limit exceeded.",
            },
            500: {
                "model": ErrorResponse,
                "description": "Unexpected server error.",
            },
        },
    )

    register_exception_handlers(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
    app.add_middleware(RequestContextMiddleware)

    app.include_router(api_router, prefix=settings.api_v1_prefix)

    # Unversioned liveness endpoint for load balancers / container probes.
    @app.get(
        "/health",
        tags=["health"],
        summary="Liveness probe (unversioned)",
        description="Returns 200 as long as the process serves HTTP. Touches no dependencies.",
        include_in_schema=True,
        responses={200: {"description": "Process is alive."}},
    )
    async def health_root() -> JSONResponse:
        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "service": settings.app_name,
                "version": settings.app_version,
                "time_detail": "see /api/v1/health for dependency checks",
            },
        )

    return app


app = create_app()
