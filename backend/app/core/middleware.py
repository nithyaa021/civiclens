"""HTTP request context middleware: request id, timing, access log."""

from __future__ import annotations

import time
import uuid

import structlog

logger = structlog.get_logger("civiclens.request")

_EXCLUDED_PATHS = frozenset({"/health", "/docs", "/redoc", "/openapi.json"})


class RequestContextMiddleware:
    """Pure-ASGI middleware (works correctly with streaming and exceptions).

    - Binds ``request_id`` to structlog context for every log inside the request.
    - Emits one structured access-log line per request with status + duration.
    - Echoes the request id back in the ``X-Request-ID`` response header.
    """

    def __init__(self, app) -> None:  # noqa: ANN001 - ASGI app type
        self.app = app

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
        }
        request_id = headers.get("x-request-id") or uuid.uuid4().hex
        path = scope.get("path", "")
        method = scope.get("method", "GET")

        structlog.contextvars.bind_contextvars(request_id=request_id, method=method, path=path)
        state = {"status_code": 500, "started": time.perf_counter()}

        async def send_wrapper(message) -> None:  # noqa: ANN001
            if message["type"] == "http.response.start":
                state["status_code"] = message["status"]
                message.setdefault("headers", [])
                message["headers"].append((b"x-request-id", request_id.encode("latin-1")))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            duration_ms = round((time.perf_counter() - state["started"]) * 1000, 2)
            logger.exception(
                "request_failed",
                request_id=request_id,
                method=method,
                path=path,
                status_code=state["status_code"],
                duration_ms=duration_ms,
            )
            raise
        finally:
            duration_ms = round((time.perf_counter() - state["started"]) * 1000, 2)
            if path not in _EXCLUDED_PATHS:
                logger.info(
                    "request_completed",
                    request_id=request_id,
                    method=method,
                    path=path,
                    status_code=state["status_code"],
                    duration_ms=duration_ms,
                )
            structlog.contextvars.clear_contextvars()
