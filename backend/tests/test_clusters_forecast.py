"""Recurring-issue clustering, priority refresh and hotspot forecasting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from bson import ObjectId
from httpx import AsyncClient

from tests.helpers import WARD1_LAT, WARD1_LNG, WARD2_LAT, WARD2_LNG, complaint_payload

GARBAGE_TEXT = (
    "The community bin outside the market overflows every morning and waste is "
    "blown into the storm drain."
)


async def _create(client: AsyncClient, headers: dict[str, str], **overrides) -> dict:  # noqa: ANN003
    resp = await client.post(
        "/api/v1/complaints", json=complaint_payload(**overrides), headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_recurring_cluster_forms_and_priority_uses_it(
    client: AsyncClient, citizen_headers: dict[str, str], officer_headers: dict[str, str], db
) -> None:
    complaint_ids = []
    for _ in range(4):
        body = await _create(
            client,
            citizen_headers,
            title="Overflowing community bin outside market",
            description=GARBAGE_TEXT,
            category="waste_management",
            location={"type": "Point", "coordinates": [WARD1_LNG + 0.0004, WARD1_LAT]},
        )
        complaint_ids.append(body["id"])

    recompute = await client.post("/api/v1/clusters/recompute", headers=officer_headers)
    assert recompute.status_code == 202, recompute.text
    summary = recompute.json()
    assert summary["clusters"] >= 1
    assert summary["priorities_refreshed"] >= 1

    listing = await client.get(
        "/api/v1/clusters/recurring",
        params={"category": "waste_management", "ward": 1, "min_count": 3},
        headers=officer_headers,
    )
    assert listing.status_code == 200, listing.text
    items = listing.json()["items"]
    assert items, "four near-identical reports must form a recurring cluster"
    cluster = max(items, key=lambda item: item["count"])
    assert cluster["count"] >= 4
    assert set(complaint_ids) <= set(cluster["complaint_ids"])
    assert cluster["affected_area"]["radius_km"] >= 0
    assert cluster["dominant_ward"] == 1

    members = await client.get(
        f"/api/v1/clusters/recurring/{cluster['id']}/members", headers=officer_headers
    )
    assert members.status_code == 200, members.text
    member_ids = {item["id"] for item in members.json()}
    assert set(complaint_ids) <= member_ids
    assert member_ids == set(cluster["complaint_ids"])

    # Cluster membership and the density term must be persisted on the complaint.
    doc = await db["complaints"].find_one({"_id": ObjectId(complaint_ids[0])})
    assert doc["cluster_id"] == cluster["id"]
    assert doc["priority"]["components"]["cluster_density"]["raw"] >= 4

    unknown = await client.get(
        "/api/v1/clusters/recurring/does-not-exist/members", headers=officer_headers
    )
    assert unknown.status_code == 404


@pytest.mark.asyncio
async def test_cluster_recompute_is_staff_only(
    client: AsyncClient, citizen_headers: dict[str, str]
) -> None:
    resp = await client.post("/api/v1/clusters/recompute", headers=citizen_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_worker_recompute_matches_the_api_path(
    client: AsyncClient, citizen_headers: dict[str, str], officer_headers: dict[str, str], db
) -> None:
    from app.workers.tasks.maintenance import recompute_analytics

    await _create(
        client,
        citizen_headers,
        title="Street lights dark on the cross road",
        description="All street lights on our lane are dark after 7 pm.",
        category="streetlight",
    )
    outcome = recompute_analytics.apply().get()
    assert outcome["complaints_scored"] >= 1
    assert outcome["clusters"] >= 0
    clusters = await db["clusters"].count_documents({})
    assert clusters == outcome["clusters"]


@pytest.mark.asyncio
async def test_forecast_endpoint_returns_fourteen_days(
    client: AsyncClient, citizen_headers: dict[str, str], db
) -> None:
    payload = complaint_payload(
        location={"type": "Point", "coordinates": [WARD2_LNG, WARD2_LAT]}
    )
    now = datetime.now(UTC)
    docs = []
    for offset in range(60):
        created = now - timedelta(days=offset)
        docs.append(
            {
                "title": "Broken road surface near market",
                "description": "The asphalt has crumbled over a 20 metre stretch.",
                "category": payload["category"],
                "severity": 3,
                "location": payload["location"],
                "address": payload["address"],
                "landmark": payload["landmark"],
                "ward": 2,
                "citizen_id": None,
                "assigned_officer_id": None,
                "status": "closed",
                "votes": 0,
                "voters": [],
                "duplicate_of": None,
                "language": None,
                "english_translation": None,
                "category_ml": None,
                "enrichment": "done",
                "priority": None,
                "sla": None,
                "resolution": None,
                "cluster_id": None,
                "attachments": [],
                "embedding": [],
                "created_at": created,
                "updated_at": created,
            }
        )
    await db["complaints"].insert_many(docs)

    resp = await client.get(
        "/api/v1/forecasts",
        params={"ward": 2, "category": "roads", "horizon_days": 14},
        headers=citizen_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ward"] == 2
    assert body["category"] == "roads"
    assert body["horizon_days"] == 14
    assert len(body["points"]) == 14
    assert all(point["predicted"] >= 0 for point in body["points"])
    dates = [point["date"] for point in body["points"]]
    assert dates == sorted(dates)
    assert body["model"]

    per_ward = await client.get(
        "/api/v1/forecasts/wards", params={"ward": 2}, headers=citizen_headers
    )
    assert per_ward.status_code == 200, per_ward.text
    assert all(item["ward"] == 2 for item in per_ward.json())
