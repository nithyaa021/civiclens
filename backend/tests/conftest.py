"""Shared pytest fixtures.

Tests run against **real** MongoDB and Redis instances (the same services the
Docker Compose file provisions).  Configure them via env vars:

    MONGO_URI  (default mongodb://localhost:27017)
    REDIS_URL  (default redis://localhost:6379/15)  <- dedicated test DB 15

The test database is dropped before and after the session.  Note that
httpx's ASGITransport does not run lifespan events, so this module performs
the startup work (logging + index creation) explicitly.
"""

from __future__ import annotations

import os
import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# --- Environment must be configured before importing the app -----------------
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_DB", f"civiclens_test_{uuid.uuid4().hex[:8]}")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("RATE_LIMIT_AUTH_LIMIT", "1000")  # effectively disabled by default
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")
os.environ.setdefault("JWT_SECRET", "unit-test-secret-not-for-production-0123456789")

from app.core.config import get_settings  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.db.indexes import ensure_indexes  # noqa: E402
from app.db.mongo import close_resources, get_database  # noqa: E402
from app.main import create_app  # noqa: E402

settings = get_settings()
assert settings.environment == "test", "tests must run with ENVIRONMENT=test"


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _database() -> None:
    """Prepare (and tear down) the test database + indexes."""
    configure_logging("WARNING", json_logs=False)
    db = get_database()
    await db.client.drop_database(db.name)
    await ensure_indexes(db)
    yield
    await db.client.drop_database(db.name)
    await close_resources()


@pytest_asyncio.fixture(scope="session")
async def app():  # noqa: ANN201 - fixture type
    return create_app()


@pytest_asyncio.fixture(scope="session")
async def client(app) -> AsyncClient:  # noqa: ANN001, ANN201
    """HTTP client wired to the ASGI app (no network socket needed)."""
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# --- Account fixtures ---------------------------------------------------------
@pytest_asyncio.fixture(scope="session")
async def citizen(client: AsyncClient) -> dict:  # noqa: ANN201
    """A registered citizen account with credentials."""
    email = f"citizen_{uuid.uuid4().hex[:8]}@example.com"
    password = "CitizenPass!2026"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "full_name": "Test Citizen", "password": password},
    )
    assert resp.status_code == 201, resp.text
    return {"email": email, "password": password, "id": resp.json()["id"]}


@pytest_asyncio.fixture(scope="session")
async def citizen_headers(client: AsyncClient, citizen: dict) -> dict[str, str]:  # noqa: ANN201
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": citizen["email"], "password": citizen["password"]},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture(scope="session")
async def admin(client: AsyncClient) -> dict:  # noqa: ANN201
    """Admin account created through the service layer (bootstrap)."""
    from app.db.mongo import get_database
    from app.models.user import Role, UserCreate
    from app.services.users import create_user

    email = f"admin_{uuid.uuid4().hex[:8]}@example.com"
    password = "AdminPass!2026"
    payload = UserCreate(
        email=email, full_name="Test Admin", password=password, role=Role.ADMIN, ward=None
    )
    user = await create_user(get_database(), payload)
    return {"email": email, "password": password, "id": user.id}


@pytest_asyncio.fixture(scope="session")
async def admin_headers(client: AsyncClient, admin: dict) -> dict[str, str]:  # noqa: ANN201
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": admin["email"], "password": admin["password"]},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}
