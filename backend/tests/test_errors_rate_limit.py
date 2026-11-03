"""Error-envelope and rate-limit behaviour."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.core.errors import ApiError, register_exception_handlers


@pytest.fixture(autouse=True)
async def _reset_rate_limits():  # noqa: ANN201 - fixture type
    """Clear rate-limit buckets before each test in this module.

    All tests share one client IP and session-scoped users, so windows must
    be reset to test limits deterministically.
    """
    from app.db.mongo import get_redis

    redis = get_redis()
    keys = [key async for key in redis.scan_iter("ratelimit:*")]
    if keys:
        await redis.delete(*keys)
    yield


# --- Error envelope -----------------------------------------------------------
async def test_unknown_route_uses_envelope(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/definitely-not-a-route")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"
    assert isinstance(body["error"]["message"], str)


async def test_method_not_allowed_uses_envelope(client: AsyncClient) -> None:
    resp = await client.delete("/api/v1/auth/login")
    assert resp.status_code == 405
    assert resp.json()["error"]["code"] == "method_not_allowed"


async def test_validation_error_lists_fields(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register", json={"email": "ok@example.com", "full_name": "A"}
    )
    assert resp.status_code == 422
    details = resp.json()["error"]["details"]
    assert any(f["field"] == "password" for f in details["fields"])


async def test_unhandled_exception_returns_clean_500() -> None:
    """Handlers registered by the app must convert crashes to the envelope."""
    boom = FastAPI()
    register_exception_handlers(boom)

    @boom.get("/boom")
    async def boom_route() -> None:
        raise RuntimeError("simulated crash")

    transport = ASGITransport(app=boom, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/boom")
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "internal_error"
    assert "simulated crash" not in body["error"]["message"]  # no internals leaked


async def test_api_error_details_survive() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/conflict")
    async def conflict_route() -> None:
        raise ApiError(409, "conflict", "Duplicate detected.", details={"duplicates": 3})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/conflict")
    assert resp.status_code == 409
    assert resp.json() == {
        "error": {
            "code": "conflict",
            "message": "Duplicate detected.",
            "details": {"duplicates": 3},
        }
    }


# --- Rate limiting ------------------------------------------------------------
@pytest.mark.asyncio
async def test_default_bucket_returns_429_over_limit(
    client: AsyncClient, citizen_headers: dict[str, str]
) -> None:
    """Lower the default limit, exhaust it for this user, then restore."""
    settings = get_settings()
    original = settings.rate_limit_default_limit
    settings.rate_limit_default_limit = 3
    try:
        allowed_codes: list[int] = []
        limited = None
        for _ in range(4):
            resp = await client.get("/api/v1/jobs/notifications", headers=citizen_headers)
            if resp.status_code == 429:
                limited = resp
                break
            allowed_codes.append(resp.status_code)

        assert limited is not None, "4th request should be rate limited"
        assert allowed_codes == [200, 200, 200]
        assert limited.headers.get("retry-after")
        body = limited.json()["error"]
        assert body["code"] == "rate_limited"
        assert body["details"]["limit"] == 3
        assert body["details"]["window_seconds"] == settings.rate_limit_default_window_seconds
    finally:
        settings.rate_limit_default_limit = original


@pytest.mark.asyncio
async def test_ratelimit_keyed_per_user_not_global(
    client: AsyncClient, citizen_headers: dict[str, str], admin_headers: dict[str, str]
) -> None:
    """Exhausting one identity's budget must not block a different identity."""
    settings = get_settings()
    original = settings.rate_limit_default_limit
    settings.rate_limit_default_limit = 1
    try:
        # Citizen consumes her budget.
        first = await client.get("/api/v1/jobs/notifications", headers=citizen_headers)
        second = await client.get("/api/v1/jobs/notifications", headers=citizen_headers)
        assert first.status_code == 200
        assert second.status_code == 429

        # Admin has a separate bucket and still passes.
        admin_call = await client.get("/api/v1/jobs/notifications", headers=admin_headers)
        assert admin_call.status_code == 200
    finally:
        settings.rate_limit_default_limit = original


@pytest.mark.asyncio
async def test_auth_bucket_is_independent_of_default(client: AsyncClient, citizen: dict) -> None:
    """The stricter auth bucket uses its own limit/window settings."""
    settings = get_settings()
    original_auth = settings.rate_limit_auth_limit
    original_default = settings.rate_limit_default_limit
    settings.rate_limit_auth_limit = 2
    settings.rate_limit_default_limit = 100
    try:
        payload = {
            "email": f"rl_{uuid.uuid4().hex[:8]}@example.com",
            "full_name": "Rate Test",
            "password": "ValidPass!2026",
        }
        r1 = await client.post("/api/v1/auth/register", json=payload)
        r2 = await client.post(
            "/api/v1/auth/register",
            json={**payload, "email": f"rl_{uuid.uuid4().hex[:8]}@example.com"},
        )
        r3 = await client.post(
            "/api/v1/auth/register",
            json={**payload, "email": f"rl_{uuid.uuid4().hex[:8]}@example.com"},
        )
        assert r1.status_code in (201, 429) and r2.status_code in (201, 429)
        assert not (r1.status_code == 429 or r2.status_code == 429), "first two must pass"
        assert r3.status_code == 429
        assert r3.headers.get("retry-after")
    finally:
        settings.rate_limit_auth_limit = original_auth
        settings.rate_limit_default_limit = original_default
