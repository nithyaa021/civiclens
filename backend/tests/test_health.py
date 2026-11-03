"""Health, liveness, OpenAPI and request-context tests."""

from __future__ import annotations

from httpx import AsyncClient


async def test_unversioned_liveness(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "CivicLens AI"


async def test_readiness_reports_dependencies(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["dependencies"]["mongo"]["status"] == "ok"
    assert body["dependencies"]["redis"]["status"] == "ok"
    assert body["dependencies"]["mongo"]["latency_ms"] >= 0
    assert body["version"]


async def test_versioned_liveness(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/health/live")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_request_id_echoed_by_server(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert "x-request-id" in resp.headers
    assert len(resp.headers["x-request-id"]) >= 8


async def test_incoming_request_id_preserved(client: AsyncClient) -> None:
    resp = await client.get("/health", headers={"X-Request-ID": "trace-me-123"})
    assert resp.headers["x-request-id"] == "trace-me-123"


async def test_openapi_document_is_complete(client: AsyncClient) -> None:
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    spec = resp.json()

    assert spec["info"]["title"] == "CivicLens AI"
    assert spec["info"]["description"], "OpenAPI description missing"
    paths = spec["paths"]
    for expected in [
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/me",
        "/api/v1/users",
        "/api/v1/jobs/embeddings",
        "/api/v1/jobs/image-analysis",
        "/api/v1/health",
        "/health",
    ]:
        assert expected in paths, f"missing path {expected}"

    # Security scheme wired for the docs' Authorize button.
    schemes = spec.get("components", {}).get("securitySchemes", {})
    assert "OAuth2Password" in schemes
    assert schemes["OAuth2Password"]["type"] == "oauth2"
    assert schemes["OAuth2Password"]["flows"]["password"]["tokenUrl"]

    # Documented tags + reusable schemas.
    assert {t["name"] for t in spec["tags"]} >= {"auth", "users", "jobs", "health"}
    schemas = spec["components"]["schemas"]
    assert {"TokenResponse", "UserPublic", "HealthResponse", "ErrorResponse"} <= set(schemas)

    # Operations carry human-facing summaries and response docs.
    login_op = paths["/api/v1/auth/login"]["post"]
    assert login_op["summary"]
    assert "200" in login_op["responses"] and "401" in login_op["responses"]


async def test_docs_and_redoc_served(client: AsyncClient) -> None:
    assert (await client.get("/docs")).status_code == 200
    assert (await client.get("/redoc")).status_code == 200
