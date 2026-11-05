"""SLA breach detection and escalation ladder (Celery beat task)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from bson import ObjectId
from httpx import AsyncClient

from app.core.config import get_settings
from app.workers.tasks.maintenance import sla_check
from tests.helpers import complaint_payload


async def _file_complaint(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/complaints", json=complaint_payload(), headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_overdue_complaint_escalates_with_audit_and_notifications(
    client: AsyncClient, citizen_headers: dict[str, str], db
) -> None:
    complaint_id = await _file_complaint(client, citizen_headers)
    settings = get_settings()
    ladder = settings.escalation_ladder

    past = datetime.now(UTC) - timedelta(hours=2)
    await db["complaints"].update_one(
        {"_id": ObjectId(complaint_id)},
        {"$set": {"sla.due_at": past, "sla.breached": False}},
    )

    outcome = sla_check.apply().get()
    assert outcome["checked"] >= 1
    assert outcome["escalated"] >= 1

    doc = await db["complaints"].find_one({"_id": ObjectId(complaint_id)})
    assert doc["sla"]["breached"] is True
    assert doc["sla"]["escalation_level"] == 1
    assert doc["sla"]["escalation_rung"] == ladder[0]
    assert doc["sla"]["breach_count"] >= 1
    assert doc["sla"]["last_breach_at"] is not None

    audit_events = [
        event
        async for event in db["audit_events"].find(
            {"complaint_id": complaint_id, "action": "sla_breached"}
        )
    ]
    assert audit_events
    assert audit_events[-1]["details"]["rung"] == ladder[0]

    notifications = [
        event
        async for event in db["notifications"].find(
            {"user_id": doc["citizen_id"], "subject": "Your report was escalated"}
        )
    ]
    assert notifications, "the reporter must be told about the escalation"

    # A second sweep within the same target window must not double-escalate.
    second = sla_check.apply().get()
    doc2 = await db["complaints"].find_one({"_id": ObjectId(complaint_id)})
    assert doc2["sla"]["escalation_level"] == 1
    assert second["escalated"] < second["checked"]


@pytest.mark.asyncio
async def test_resolved_or_closed_complaints_are_not_escalated(
    client: AsyncClient, citizen_headers: dict[str, str], db
) -> None:
    complaint_id = await _file_complaint(client, citizen_headers)
    past = datetime.now(UTC) - timedelta(days=1)
    await db["complaints"].update_one(
        {"_id": ObjectId(complaint_id)},
        {"$set": {"sla.due_at": past, "status": "closed"}},
    )
    sla_check.apply().get()
    doc = await db["complaints"].find_one({"_id": ObjectId(complaint_id)})
    assert doc["sla"]["escalation_level"] == 0
    assert doc["sla"]["breached"] is False


@pytest.mark.asyncio
async def test_complaint_carries_its_category_sla_target(
    client: AsyncClient, citizen_headers: dict[str, str]
) -> None:
    settings = get_settings()
    for category in ("water_supply", "drainage", "parks_trees"):
        resp = await client.post(
            "/api/v1/complaints",
            json=complaint_payload(category=category, title=f"{category} issue near park"),
            headers=citizen_headers,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["sla"]["target_hours"] == settings.sla_targets_hours[category]
        expected_due = datetime.fromisoformat(body["created_at"]) + timedelta(
            hours=settings.sla_targets_hours[category]
        )
        assert datetime.fromisoformat(body["sla"]["due_at"]) == expected_due
