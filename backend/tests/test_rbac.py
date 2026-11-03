"""Role-based access control tests."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_citizen_forbidden_from_admin_endpoints(
    client: AsyncClient, citizen_headers: dict[str, str]
) -> None:
    post_body = {"email": "x@example.com", "full_name": "X", "password": "ValidPass!2026"}

    get_resp = await client.get("/api/v1/users", headers=citizen_headers)
    assert get_resp.status_code == 403, f"GET /users -> {get_resp.status_code}"
    assert get_resp.json()["error"]["code"] == "forbidden"

    post_resp = await client.post("/api/v1/users", json=post_body, headers=citizen_headers)
    assert post_resp.status_code == 403, f"POST /users -> {post_resp.status_code}"
    assert post_resp.json()["error"]["code"] == "forbidden"


@pytest.mark.asyncio
async def test_anonymous_forbidden_from_admin_endpoints(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_can_list_and_search_users(
    client: AsyncClient, admin_headers: dict[str, str], citizen: dict
) -> None:
    resp = await client.get(
        "/api/v1/users", params={"page": 1, "page_size": 5}, headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    page = resp.json()
    assert page["total"] >= 2
    assert len(page["items"]) <= 5
    assert all("password" not in str(item).lower() for item in page["items"])

    search = await client.get(
        "/api/v1/users", params={"search": citizen["email"]}, headers=admin_headers
    )
    assert search.status_code == 200
    assert search.json()["items"][0]["email"] == citizen["email"]


@pytest.mark.asyncio
async def test_admin_provisions_ward_officer_and_assigns_ward(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    email = f"officer_{uuid.uuid4().hex[:8]}@example.com"
    create = await client.post(
        "/api/v1/users",
        json={
            "email": email,
            "full_name": "Ward Officer",
            "password": "OfficerPass!2026",
            "role": "ward_officer",
            "ward": 12,
        },
        headers=admin_headers,
    )
    assert create.status_code == 201, create.text
    officer = create.json()
    assert officer["role"] == "ward_officer"
    assert officer["ward"] == 12

    # Officer can authenticate and reaches officer-permitted code paths.
    login = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": "OfficerPass!2026"}
    )
    assert login.status_code == 200
    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["role"] == "ward_officer"


@pytest.mark.asyncio
async def test_officer_requires_ward_number(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/api/v1/users",
        json={
            "email": f"noward_{uuid.uuid4().hex[:8]}@example.com",
            "full_name": "No Ward",
            "password": "ValidPass!2026",
            "role": "ward_officer",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 422
    fields = [f["field"] for f in resp.json()["error"]["details"]["fields"]]
    assert "ward" in fields


@pytest.mark.asyncio
async def test_role_change_applies_to_existing_tokens(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """After demotion, the user's refreshed tokens carry the new role."""
    email = f"demote_{uuid.uuid4().hex[:8]}@example.com"
    create = await client.post(
        "/api/v1/users",
        json={
            "email": email,
            "full_name": "Temp Officer",
            "password": "ValidPass!2026",
            "role": "ward_officer",
            "ward": 3,
        },
        headers=admin_headers,
    )
    assert create.status_code == 201
    user_id = create.json()["id"]

    demote = await client.patch(
        f"/api/v1/users/{user_id}/role", json={"role": "citizen"}, headers=admin_headers
    )
    assert demote.status_code == 200
    assert demote.json()["role"] == "citizen"

    # Role-change revokes refresh tokens; new login carries the new role.
    login = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": "ValidPass!2026"}
    )
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "citizen"


@pytest.mark.asyncio
async def test_last_admin_cannot_be_demoted(
    client: AsyncClient, admin_headers: dict[str, str], admin: dict
) -> None:
    resp = await client.patch(
        f"/api/v1/users/{admin['id']}/role",
        json={"role": "citizen"},
        headers=admin_headers,
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["details"]["reason"] == "last_admin"


@pytest.mark.asyncio
async def test_admin_cannot_deactivate_self(
    client: AsyncClient, admin_headers: dict[str, str], admin: dict
) -> None:
    resp = await client.patch(
        f"/api/v1/users/{admin['id']}/status",
        json={"status": "inactive"},
        headers=admin_headers,
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["details"]["reason"] == "self"


@pytest.mark.asyncio
async def test_unknown_user_id_404(client: AsyncClient, admin_headers: dict[str, str]) -> None:
    resp = await client.get("/api/v1/users/665f1c2e9b0d4a2f18c3ab99", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
