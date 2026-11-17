"""Public demo sessions: anonymised perspective picker without a login form.

The demo must never become a way to impersonate a real account, so these tests
focus as much on the guard rails as on the happy path.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.core.security import hash_password
from app.db.mongo import get_database
from app.services.demo import DEMO_EMAIL_DOMAIN


@pytest.fixture(autouse=True)
async def demo_accounts():
    """Seed the synthetic accounts the demo directory expects, then remove them.

    The suite shares one database, and an extra `admin` account would make the
    "last admin" guard in test_rbac stop firing. Auto-cleanup keeps the demo
    fixture from leaking into unrelated tests.
    """
    from datetime import UTC, datetime

    db = get_database()
    now = datetime.now(UTC)
    docs = [
        {
            "email": f"admin{DEMO_EMAIL_DOMAIN}",
            "full_name": "Demo Administrator",
            "role": "admin",
            "ward": None,
            "status": "active",
            "password_hash": hash_password("Admin#12345"),
            "created_at": now,
        },
        {
            "email": f"officer7{DEMO_EMAIL_DOMAIN}",
            "full_name": "Ward 7 Officer",
            "role": "ward_officer",
            "ward": 7,
            "status": "active",
            "password_hash": hash_password("Officer#12345"),
            "created_at": now,
        },
        {
            "email": f"citizen1{DEMO_EMAIL_DOMAIN}",
            "full_name": "Demo Citizen",
            "role": "citizen",
            "ward": 7,
            "status": "active",
            "password_hash": hash_password("Citizen#12345"),
            "created_at": now,
        },
    ]
    emails = [doc["email"] for doc in docs]
    try:
        for doc in docs:
            await db["users"].update_one(
                {"email": doc["email"]},
                {"$setOnInsert": doc},
                upsert=True,
            )
        yield
    finally:
        await db["users"].delete_many({"email": {"$in": emails}})


async def test_demo_directory_lists_seeded_perspectives(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/demo")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enabled"] is True
    assert body["default"] == "admin"
    ids = [item["id"] for item in body["perspectives"]]
    assert ids[:2] == ["admin", "ward-7"]
    assert "citizen" in ids

    admin = next(item for item in body["perspectives"] if item["id"] == "admin")
    assert admin["role"] == "admin"
    assert admin["ward"] is None

    ward = next(item for item in body["perspectives"] if item["id"] == "ward-7")
    assert ward["role"] == "ward_officer"
    assert ward["ward"] == 7


async def test_demo_session_issues_working_tokens(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/demo-session", json={"perspective": "ward-7"})

    assert resp.status_code == 200, resp.text
    pair = resp.json()
    assert pair["user"]["role"] == "ward_officer"
    assert pair["user"]["ward"] == 7
    assert pair["access_token"]

    headers = {"Authorization": f"Bearer {pair['access_token']}"}
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["user"]["ward"] == 7

    # The session really is ward-scoped, not a bypass of the role guards.
    overview = await client.get("/api/v1/analytics/overview", headers=headers)
    assert overview.status_code == 200
    assert overview.json()["scope"] == "ward"
    assert overview.json()["ward"] == 7


async def test_demo_session_rejects_unknown_perspective(client: AsyncClient) -> None:
    for bad in ["nope", "ward-999", "admin@civiclens.dev"]:
        resp = await client.post("/api/v1/auth/demo-session", json={"perspective": bad})
        assert resp.status_code == 404, bad
        assert resp.json()["error"]["code"] == "not_found"


async def test_demo_ignores_non_seeded_accounts_on_demo_domain(client: AsyncClient) -> None:
    """A registered look-alike address must never become a perspective."""
    db = get_database()
    impostor = f"mallory{uuid.uuid4().hex[:8]}{DEMO_EMAIL_DOMAIN}"
    await db["users"].insert_one(
        {
            "email": impostor,
            "full_name": "Mallory",
            "role": "admin",
            "ward": None,
            "status": "active",
            "password_hash": hash_password("Mallory#12345"),
        }
    )

    directory = await client.get("/api/v1/auth/demo")
    assert directory.status_code == 200
    emails = [item["id"] for item in directory.json()["perspectives"]]
    assert "admin" in emails  # the seeded one still wins

    # And the impostor cannot be selected by email.
    resp = await client.post("/api/v1/auth/demo-session", json={"perspective": impostor})
    assert resp.status_code == 404

    # Leave the shared test database as we found it: an extra admin here would
    # stop the "last admin" guard in test_rbac from firing.
    await db["users"].delete_one({"email": impostor})


async def test_demo_session_can_be_disabled(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "demo_mode", False, raising=False)

    directory = await client.get("/api/v1/auth/demo")
    assert directory.status_code == 200
    assert directory.json() == {"enabled": False, "default": None, "perspectives": []}

    resp = await client.post("/api/v1/auth/demo-session", json={"perspective": "admin"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "demo_disabled"


async def test_staff_routes_still_require_a_token(client: AsyncClient) -> None:
    """Removing the login *form* must not remove authentication."""
    for path in ["/api/v1/complaints", "/api/v1/analytics/overview", "/api/v1/users/officers"]:
        resp = await client.get(path)
        assert resp.status_code == 401, path
