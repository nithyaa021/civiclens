"""Authority analytics, public transparency, notes and bulk actions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from bson import ObjectId
from httpx import AsyncClient

from app.data.corpus import generate_wards
from tests.helpers import WARD1_LAT, WARD1_LNG, WARD2_LAT, WARD2_LNG, complaint_payload


async def _create(client: AsyncClient, headers: dict[str, str], **overrides) -> dict:
    resp = await client.post(
        "/api/v1/complaints", json=complaint_payload(**overrides), headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_public_stats_are_anonymous_and_include_resolutions(
    client: AsyncClient, db, citizen_headers: dict[str, str]
) -> None:
    created = await _create(
        client,
        citizen_headers,
        title="Public transparency fixture",
        category="streetlight",
    )
    now = datetime.now(UTC)
    resolved_at = now - timedelta(days=2)
    await db["complaints"].update_one(
        {"_id": ObjectId(created["id"])},
        {
            "$set": {
                "status": "closed",
                "resolved_at": resolved_at,
                "closed_at": now - timedelta(days=1, hours=20),
                "updated_at": now - timedelta(days=1, hours=20),
                "resolution": {
                    "after_media_id": "665f1c2e9b0d4a2f18c3ab71",
                    "officer_id": None,
                    "note": "Lamp replaced and tested by the ward electrical crew.",
                    "verification": {
                        "after_media_id": "665f1c2e9b0d4a2f18c3ab71",
                        "confidence": 0.93,
                        "passed": True,
                        "features": {"clip_similarity": 0.61, "ssim_delta": 0.22},
                        "model_version": "clip-siamese-logreg-v1",
                        "note": None,
                        "verified_at": resolved_at,
                    },
                    "citizen_decision": "confirmed",
                    "decision_note": None,
                    "decided_at": now - timedelta(days=1, hours=21),
                    "created_at": resolved_at,
                },
            }
        },
    )

    resp = await client.get("/api/v1/public/stats")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["wards"] and len(body["wards"]) == len(generate_wards())
    assert body["totals"]["total"] >= 1
    assert body["recent_resolutions"]
    assert any(
        item["title"] == "Public transparency fixture" for item in body["recent_resolutions"]
    )
    assert "citizen_id" not in resp.text
    assert "assigned_officer_id" not in resp.text
    assert "citizen@" not in resp.text
    assert resp.headers["cache-control"] == "public, max-age=60"


@pytest.mark.asyncio
async def test_overview_and_map_respect_role_scope(
    client: AsyncClient,
    officer_headers: dict[str, str],
    admin_headers: dict[str, str],
    citizen_headers: dict[str, str],
) -> None:
    await db_insert_sample(client, officer_headers, WARD1_LNG, WARD1_LAT, "Ward one sample")
    await db_insert_sample(client, admin_headers, WARD2_LNG, WARD2_LAT, "Ward two sample")

    forbidden = await client.get("/api/v1/analytics/overview", headers=citizen_headers)
    assert forbidden.status_code == 403

    ward = await client.get("/api/v1/analytics/overview", headers=officer_headers)
    assert ward.status_code == 200, ward.text
    assert ward.json()["scope"] == "ward"
    assert ward.json()["ward"] == 1
    assert len(ward.json()["trend"]) == 30

    admin = await client.get("/api/v1/analytics/overview", headers=admin_headers)
    assert admin.status_code == 200
    assert admin.json()["scope"] == "all"

    map_resp = await client.get("/api/v1/analytics/map", headers=officer_headers)
    assert map_resp.status_code == 200, map_resp.text
    assert map_resp.json()["items"]
    assert all(item["ward"] == 1 for item in map_resp.json()["items"])

    officers = await client.get("/api/v1/users/officers", headers=officer_headers)
    assert officers.status_code == 200
    assert any(item["ward"] == 1 for item in officers.json())

    denied = await client.get("/api/v1/users/officers", headers=citizen_headers)
    assert denied.status_code == 403


async def db_insert_sample(
    client: AsyncClient, headers: dict[str, str], lng: float, lat: float, title: str
) -> dict:
    """Small helper kept separate to make the scope test readable."""
    return await _create(
        client,
        headers,
        title=f"{title} {datetime.now(UTC).timestamp()}",
        location={"type": "Point", "coordinates": [lng, lat]},
    )


@pytest.mark.asyncio
async def test_internal_notes_and_bulk_actions(
    client: AsyncClient,
    citizen_headers: dict[str, str],
    officer_headers: dict[str, str],
    officer: dict,
    admin_headers: dict[str, str],
) -> None:
    first = await _create(client, citizen_headers, title="Bulk assignment pothole one")
    second = await _create(client, citizen_headers, title="Bulk assignment pothole two")

    note_resp = await client.post(
        f"/api/v1/complaints/{first['id']}/notes",
        json={"note": "Inspection scheduled with the roads contractor for Monday."},
        headers=officer_headers,
    )
    assert note_resp.status_code == 201, note_resp.text
    notes = await client.get(
        f"/api/v1/complaints/{first['id']}/notes", headers=officer_headers
    )
    assert notes.status_code == 200
    assert notes.json()["total"] == 1
    assert notes.json()["items"][0]["author_name"] == "Ward One Officer"

    citizen_notes = await client.get(
        f"/api/v1/complaints/{first['id']}/notes", headers=citizen_headers
    )
    assert citizen_notes.status_code == 403

    bulk = await client.post(
        "/api/v1/complaints/bulk/assign",
        json={"complaint_ids": [first["id"], second["id"]], "officer_id": officer["id"]},
        headers=admin_headers,
    )
    assert bulk.status_code == 200, bulk.text
    assert bulk.json()["updated"] == 2
    assert bulk.json()["failed"] == []
    assert all(item["assigned_officer_id"] == officer["id"] for item in bulk.json()["items"])

    transitioned = await client.post(
        "/api/v1/complaints/bulk/status",
        json={
            "complaint_ids": [first["id"], second["id"]],
            "status": "in_progress",
            "note": "Crew dispatched.",
        },
        headers=officer_headers,
    )
    assert transitioned.status_code == 200, transitioned.text
    assert transitioned.json()["updated"] == 2
    assert all(item["status"] == "in_progress" for item in transitioned.json()["items"])
