"""Complaint lifecycle: filing, similarity, votes, workflow and visibility."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.helpers import WARD1_LAT, WARD1_LNG, WARD2_LAT, WARD2_LNG, complaint_payload


async def _create(client: AsyncClient, headers: dict[str, str], **overrides) -> dict:  # noqa: ANN003
    resp = await client.post(
        "/api/v1/complaints", json=complaint_payload(**overrides), headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_filing_assigns_officer_starts_sla_and_scores_priority(
    client: AsyncClient, citizen_headers: dict[str, str], officer: dict
) -> None:
    body = await _create(client, citizen_headers)
    assert body["ward"] == 1
    assert body["status"] == "assigned"
    assert body["assigned_officer_id"] == officer["id"]

    sla = body["sla"]
    assert sla["target_hours"] == 72  # roads target from settings
    due_at = body["created_at"]
    assert sla["due_at"] > due_at
    assert sla["breached"] is False
    assert sla["escalation_level"] == 0

    priority = body["priority"]
    assert 0 <= priority["score"] <= 100
    assert set(priority["components"]) == {
        "severity",
        "frequency",
        "cluster_density",
        "age_unresolved",
        "sensitive_proximity",
    }
    contributions = sum(c["contribution"] for c in priority["components"].values())
    assert priority["score"] == pytest.approx(contributions, abs=0.05)


@pytest.mark.asyncio
async def test_outside_service_area_and_unknown_duplicate_are_rejected(
    client: AsyncClient, citizen_headers: dict[str, str]
) -> None:
    outside = await client.post(
        "/api/v1/complaints",
        json=complaint_payload(location={"type": "Point", "coordinates": [77.0, 12.0]}),
        headers=citizen_headers,
    )
    assert outside.status_code == 400
    assert outside.json()["error"]["code"] == "outside_service_area"

    duplicate = await client.post(
        "/api/v1/complaints",
        json=complaint_payload(duplicate_of="not-an-object-id"),
        headers=citizen_headers,
    )
    assert duplicate.status_code == 400
    assert duplicate.json()["error"]["code"] == "unknown_duplicate"


@pytest.mark.asyncio
async def test_visibility_of_reporter_identity(
    client: AsyncClient,
    citizen_headers: dict[str, str],
    citizen2_headers: dict[str, str],
    officer_headers: dict[str, str],
) -> None:
    created = await _create(client, citizen_headers)
    url = f"/api/v1/complaints/{created['id']}"

    own = await client.get(url, headers=citizen_headers)
    assert own.status_code == 200
    assert own.json()["citizen_id"] == created["citizen_id"]

    other = await client.get(url, headers=citizen2_headers)
    assert other.status_code == 200
    assert other.json()["citizen_id"] is None

    staff = await client.get(url, headers=officer_headers)
    assert staff.status_code == 200
    assert staff.json()["citizen_id"] == created["citizen_id"]


@pytest.mark.asyncio
async def test_similar_issues_surface_the_cross_language_duplicate(
    client: AsyncClient, citizen_headers: dict[str, str]
) -> None:
    created = await _create(client, citizen_headers)
    resp = await client.post(
        "/api/v1/complaints/similar",
        json={
            "text": (
                "A large pothole has formed near the bus stop after the rains. "
                "Two-wheelers are skidding and it is dangerous at night."
            ),
            "location": {"type": "Point", "coordinates": [WARD1_LNG, WARD1_LAT]},
            "category": "roads",
            "radius_km": 1.0,
        },
        headers=citizen_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"], body
    ids = [item["complaint"]["id"] for item in body["items"]]
    assert created["id"] in ids
    top = body["items"][0]
    assert top["score"] >= body["min_score"]
    assert top["distance_km"] is not None and top["distance_km"] < 0.05


@pytest.mark.asyncio
async def test_upvotes_are_idempotent_and_retractable(
    client: AsyncClient, citizen_headers: dict[str, str]
) -> None:
    created = await _create(client, citizen_headers)
    url = f"/api/v1/complaints/{created['id']}/vote"
    assert created["votes"] == 0

    first = await client.post(url, headers=citizen_headers)
    assert first.status_code == 200
    assert first.json()["votes"] == 1

    second = await client.post(url, headers=citizen_headers)
    assert second.json()["votes"] == 1

    removed = await client.delete(url, headers=citizen_headers)
    assert removed.json()["votes"] == 0

    again = await client.delete(url, headers=citizen_headers)
    assert again.json()["votes"] == 0


@pytest.mark.asyncio
async def test_workflow_is_transition_guarded(
    client: AsyncClient,
    citizen_headers: dict[str, str],
    officer_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    created = await _create(client, citizen_headers)
    url = f"/api/v1/complaints/{created['id']}/status"

    citizen = await client.patch(url, json={"status": "in_progress"}, headers=citizen_headers)
    assert citizen.status_code == 403

    illegal = await client.patch(
        url, json={"status": "closed"}, headers=officer_headers
    )
    assert illegal.status_code == 400

    to_progress = await client.patch(
        url, json={"status": "in_progress", "note": "crew dispatched"}, headers=officer_headers
    )
    assert to_progress.status_code == 200, to_progress.text
    assert to_progress.json()["status"] == "in_progress"

    unverified = await client.patch(
        url, json={"status": "resolved"}, headers=officer_headers
    )
    assert unverified.status_code == 409
    assert unverified.json()["error"]["details"]["reason"] == "verification_required"

    admin_resolve = await client.patch(url, json={"status": "resolved"}, headers=admin_headers)
    assert admin_resolve.status_code == 200, admin_resolve.text

    close = await client.patch(url, json={"status": "closed"}, headers=admin_headers)
    assert close.status_code == 200, close.text
    assert close.json()["status"] == "closed"


@pytest.mark.asyncio
async def test_officers_cannot_touch_other_wards(
    client: AsyncClient,
    citizen_headers: dict[str, str],
    officer_headers: dict[str, str],
    officer_ward2: dict,
) -> None:
    other_ward = await _create(
        client,
        citizen_headers,
        location={"type": "Point", "coordinates": [WARD2_LNG, WARD2_LAT]},
    )
    assert other_ward["ward"] == 2
    resp = await client.patch(
        f"/api/v1/complaints/{other_ward['id']}/status",
        json={"status": "in_progress"},
        headers=officer_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_audit_trail_records_creation_and_assignment(
    client: AsyncClient, citizen_headers: dict[str, str]
) -> None:
    created = await _create(client, citizen_headers)
    resp = await client.get(
        f"/api/v1/complaints/{created['id']}/audit", headers=citizen_headers
    )
    assert resp.status_code == 200, resp.text
    actions = [event["action"] for event in resp.json()["items"]]
    assert actions[0] == "created"
    assert "auto_assigned" in actions


@pytest.mark.asyncio
async def test_listing_filters_by_category_and_ward(
    client: AsyncClient, citizen_headers: dict[str, str]
) -> None:
    created = await _create(
        client, citizen_headers, category="streetlight", title="Lamp post dark near school"
    )
    resp = await client.get(
        "/api/v1/complaints",
        params={"category": "streetlight", "ward": 1, "sort": "priority"},
        headers=citizen_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1
    assert all(item["category"] == "streetlight" for item in body["items"])
    assert created["id"] in {item["id"] for item in body["items"]}


@pytest.mark.asyncio
async def test_filtering_by_mine_uses_the_caller_identity(
    client: AsyncClient, citizen_headers: dict[str, str], citizen2_headers: dict[str, str]
) -> None:
    mine = await _create(client, citizen_headers)
    theirs = await client.get(
        "/api/v1/complaints", params={"mine": "true"}, headers=citizen2_headers
    )
    assert theirs.status_code == 200
    ids = {item["id"] for item in theirs.json()["items"]}
    assert mine["id"] not in ids

    ours = await client.get(
        "/api/v1/complaints", params={"mine": "true"}, headers=citizen_headers
    )
    assert mine["id"] in {item["id"] for item in ours.json()["items"]}
