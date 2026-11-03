"""Centralised error handling.

Every error leaving the API uses a single, documented envelope:

.. code-block:: json

    {"error": {"code": "not_found", "message": "User not found", "details": {}}}

Handlers are registered in :func:`app.main.create_app`.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

logger = get_logger("civiclens.errors")

# Fallback messages for status codes raised without an explicit code.
_HTTP_STATUS_DETAILS: dict[int, tuple[str, str]] = {
    400: ("bad_request", "The request could not be processed."),
    401: ("unauthenticated", "Authentication credentials were missing or invalid."),
    403: ("forbidden", "You do not have permission to perform this action."),
    404: ("not_found", "The requested resource was not found."),
    405: ("method_not_allowed", "HTTP method not allowed for this endpoint."),
    409: ("conflict", "The request conflicts with the current resource state."),
    422: ("validation_error", "Request validation failed."),
    429: ("rate_limited", "Too many requests. Please retry later."),
    500: ("internal_error", "An unexpected error occurred. Please try again."),
}


class ApiError(Exception):
    """Application error carrying an HTTP status, machine code and message."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers or {}


class NotFoundError(ApiError):
    def __init__(self, resource: str, identifier: str | None = None) -> None:
        message = f"{resource} not found"
        if identifier is not None:
            message = f"{resource} {identifier!r} not found"
        super().__init__(404, "not_found", message)


class ConflictError(ApiError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(409, "conflict", message, details)


class UnauthorizedError(ApiError):
    def __init__(
        self, message: str = "Could not validate credentials.", code: str = "unauthenticated"
    ) -> None:
        super().__init__(
            401,
            code,
            message,
            headers={"WWW-Authenticate": "Bearer"},
        )


class ForbiddenError(ApiError):
    def __init__(self, message: str = "Insufficient permissions for this action.") -> None:
        super().__init__(403, "forbidden", message)


class RateLimitExceeded(ApiError):
    def __init__(self, retry_after_seconds: int, limit: int, window_seconds: int) -> None:
        super().__init__(
            429,
            "rate_limited",
            f"Rate limit exceeded: at most {limit} requests every {window_seconds}s.",
            details={"limit": limit, "window_seconds": window_seconds},
            headers={"Retry-After": str(max(1, retry_after_seconds))},
        )


def error_payload(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the canonical error envelope."""
    body: dict[str, Any] = {"code": code, "message": message}
    if details:
        body["details"] = details
    return {"error": body}


def _http_exception_response(exc: HTTPException | StarletteHTTPException) -> JSONResponse:
    default_code, default_message = _HTTP_STATUS_DETAILS.get(
        exc.status_code, ("http_error", "Request failed.")
    )
    detail = exc.detail
    if isinstance(detail, dict) and {"code", "message"} <= set(detail):
        code = str(detail["code"])
        message = str(detail["message"])
        details = detail.get("details")
    elif isinstance(detail, str) and detail and detail != default_message:
        code, message, details = default_code, detail, None
    else:
        code, message, details = default_code, default_message, None

    headers = dict(exc.headers or {})
    if exc.status_code == 401:
        headers.setdefault("WWW-Authenticate", "Bearer")

    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(code, message, details if isinstance(details, dict) else None),
        headers=headers,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach every error handler to the application instance."""

    @app.exception_handler(ApiError)
    async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        log = logger.bind(
            path=request.url.path,
            method=request.method,
            status_code=exc.status_code,
            error_code=exc.code,
        )
        if exc.status_code >= 500:
            log.error("api_error", message=exc.message, exc_info=True)
        else:
            log.info("api_error", message=exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(exc.code, exc.message, exc.details),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Pydantic errors contain non-JSON-safe values (ctx with exceptions).
        fields = [
            {
                "field": ".".join(str(part) for part in error["loc"] if part != "body"),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        logger.info(
            "request_validation_failed",
            path=request.url.path,
            method=request.method,
            field_count=len(fields),
        )
        return JSONResponse(
            status_code=422,
            content=error_payload(
                "validation_error",
                "Request validation failed.",
                {"fields": fields},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _http_exception_response(exc)

    @app.exception_handler(Exception)
    async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            exc_info=True,
        )
        code, message = _HTTP_STATUS_DETAILS[500]
        return JSONResponse(status_code=500, content=error_payload(code, message))
