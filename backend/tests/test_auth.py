"""End-to-end auth flow tests: register -> login -> use -> refresh -> logout."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


async def _register(client: AsyncClient, suffix: str | None = None) -> dict:
    email = f"user_{suffix or uuid.uuid4().hex[:8]}@example.com"
    password = "ValidPass!2026"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "full_name": "Flow Tester", "password": password},
    )
    assert resp.status_code == 201, resp.text
    return {"email": email, "password": password, "user": resp.json()}


async def _login(client: AsyncClient, email: str, password: str):
    return await client.post("/api/v1/auth/login", data={"username": email, "password": password})


@pytest.mark.asyncio
async def test_register_returns_public_user(client: AsyncClient) -> None:
    account = await _register(client)
    user = account["user"]
    assert user["email"] == account["email"]
    assert user["role"] == "citizen"
    assert user["status"] == "active"
    assert "password" not in str(user).lower()
    assert "id" in user


@pytest.mark.asyncio
async def test_register_duplicate_email_conflicts(client: AsyncClient) -> None:
    account = await _register(client)
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": account["email"].upper(),  # case-insensitive uniqueness
            "full_name": "Someone Else",
            "password": "AnotherPass!2026",
        },
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,expected_field",
    [
        ({"email": "bad-email", "full_name": "X", "password": "ValidPass!2026"}, "email"),
        ({"email": "ok@example.com", "full_name": "X", "password": "12345678"}, "password"),
        ({"email": "ok@example.com", "full_name": "X", "password": "short"}, "password"),
    ],
)
async def test_register_validation_errors(
    client: AsyncClient, payload: dict, expected_field: str
) -> None:
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 422
    body = resp.json()["error"]
    assert body["code"] == "validation_error"
    fields = [f["field"] for f in body["details"]["fields"]]
    assert expected_field in fields


@pytest.mark.asyncio
async def test_login_success_and_me(client: AsyncClient) -> None:
    account = await _register(client)
    resp = await _login(client, account["email"], account["password"])
    assert resp.status_code == 200, resp.text
    tokens = resp.json()
    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] > 0
    assert tokens["user"]["email"] == account["email"]

    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["user"]["email"] == account["email"]


@pytest.mark.asyncio
async def test_login_wrong_password_is_401(client: AsyncClient) -> None:
    account = await _register(client)
    resp = await _login(client, account["password"], account["password"])  # wrong combo
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_credentials"
    # Unknown email must return the identical code/message (no enumeration).
    resp2 = await _login(client, "ghost@example.com", "whatever123")
    assert resp2.status_code == 401
    assert resp2.json()["error"]["message"] == resp.json()["error"]["message"]


@pytest.mark.asyncio
async def test_missing_and_bad_tokens_rejected(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer nonsense"})
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"
    assert resp.json()["error"]["code"] in {"unauthenticated", "token_invalid"}


@pytest.mark.asyncio
async def test_refresh_rotation_and_replay_rejected(client: AsyncClient, citizen: dict) -> None:
    login = await _login(client, citizen["email"], citizen["password"])
    first = login.json()

    # Rotate: old refresh token must stop working immediately (single use).
    rotate = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert rotate.status_code == 200, rotate.text
    second = rotate.json()
    assert second["access_token"] != first["access_token"]
    assert second["refresh_token"] != first["refresh_token"]

    replay = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "refresh_revoked"

    # The rotated token still works.
    again = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]}
    )
    assert again.status_code == 200


@pytest.mark.asyncio
async def test_access_token_rejected_as_refresh_token(client: AsyncClient) -> None:
    account = await _register(client)
    login = await _login(client, account["email"], account["password"])
    access = login.json()["access_token"]
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": access})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "token_wrong_type"


@pytest.mark.asyncio
async def test_logout_revokes_refresh_token(client: AsyncClient) -> None:
    account = await _register(client)
    login = await _login(client, account["email"], account["password"])
    tokens = login.json()

    out = await client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert out.status_code == 200

    refresh = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refresh.status_code == 401
    assert refresh.json()["error"]["code"] == "refresh_revoked"


@pytest.mark.asyncio
async def test_deactivated_user_locked_out(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    account = await _register(client)
    login = await _login(client, account["email"], account["password"])
    tokens = login.json()

    user_id = tokens["user"]["id"]
    patch = await client.patch(
        f"/api/v1/users/{user_id}/status",
        json={"status": "inactive"},
        headers=admin_headers,
    )
    assert patch.status_code == 200, patch.text

    # New login refused.
    again = await _login(client, account["email"], account["password"])
    assert again.status_code == 401
    assert again.json()["error"]["code"] == "user_inactive"

    # Existing access token refused on next use.
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.status_code == 401
    assert me.json()["error"]["code"] == "user_inactive"

    # Reactivate so session-scoped fixtures stay usable.
    restore = await client.patch(
        f"/api/v1/users/{user_id}/status",
        json={"status": "active"},
        headers=admin_headers,
    )
    assert restore.status_code == 200
