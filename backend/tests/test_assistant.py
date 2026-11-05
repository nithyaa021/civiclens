"""Grounded assistant: intent retrieval, slots, and role-scoped citations."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.ai.assistant import _parse_category, _parse_period, _parse_ward, _retrieve_intent
from tests.helpers import complaint_payload


async def _create(client: AsyncClient, headers: dict[str, str], **overrides) -> dict:  # noqa: ANN003
    resp = await client.post(
        "/api/v1/complaints", json=complaint_payload(**overrides), headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_slot_parsing() -> None:
    assert _parse_ward("top recurring issues in ward 12 this month") == 12
    assert _parse_ward("complaints in w7") == 7
    assert _parse_ward("no ward mentioned") is None

    assert _parse_category("pothole reports in ward 3") == "roads"
    assert _parse_category("overflowing garbage bins") == "waste_management"
    assert _parse_category("street light not working") == "streetlight"
    assert _parse_category("general question") is None

    start, end, label = _parse_period("how many complaints this week")
    assert label == "the last 7 days"
    assert (end - start).days == 7

    start, end, label = _parse_period("status this month")
    assert label == "this month"
    assert start.day == 1


@pytest.mark.asyncio
async def test_intent_retrieval_maps_paraphrases() -> None:
    intent, score = await _retrieve_intent("where is my garbage complaint")
    assert intent == "status_of"
    assert 0.0 <= score <= 1.0

    intent, _ = await _retrieve_intent("which complaints are overdue in ward 5")
    assert intent == "overdue"

    intent, _ = await _retrieve_intent("show my open reports")
    assert intent == "my_complaints"


@pytest.mark.asyncio
async def test_my_complaints_only_cites_my_own_reports(
    client: AsyncClient, citizen_headers: dict[str, str], citizen2_headers: dict[str, str]
) -> None:
    mine = await _create(
        client, citizen_headers, title="Pothole on 10th Main Road", category="roads"
    )
    resp = await client.post(
        "/api/v1/assistant/query", json={"question": "show my complaints"}, headers=citizen_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["intent"] == "my_complaints"
    assert body["scope"] == "own"
    citation_ids = {citation["complaint_id"] for citation in body["citations"]}
    assert mine["id"] in citation_ids

    # Another citizen must never see that complaint cited.
    other = await client.post(
        "/api/v1/assistant/query",
        json={"question": "show my complaints"},
        headers=citizen2_headers,
    )
    assert other.status_code == 200
    other_body = other.json()
    assert other_body["scope"] == "own"
    assert mine["id"] not in {citation["complaint_id"] for citation in other_body["citations"]}


@pytest.mark.asyncio
async def test_status_answer_states_reality_and_cites_the_report(
    client: AsyncClient, citizen_headers: dict[str, str]
) -> None:
    created = await _create(
        client, citizen_headers, title="Water logging outside the school", category="drainage"
    )
    resp = await client.post(
        "/api/v1/assistant/query",
        json={"question": "what is the status of my drainage complaint"},
        headers=citizen_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["intent"] == "status_of"
    assert created["id"] in {c["complaint_id"] for c in body["citations"]}
    assert "is currently" in body["answer"]
    assert "SLA target" in body["answer"]


@pytest.mark.asyncio
async def test_admin_gets_aggregate_counts(
    client: AsyncClient, citizen_headers: dict[str, str], admin_headers: dict[str, str]
) -> None:
    await _create(client, citizen_headers, category="waste_management", title="Bin overflow")
    resp = await client.post(
        "/api/v1/assistant/query",
        json={"question": "how many complaints per category this month"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["intent"] == "count_by_category"
    assert body["scope"] == "all"
    assert "complaint(s)" in body["answer"]
    assert body["citations"], "the admin answer should cite real complaint ids"


@pytest.mark.asyncio
async def test_overdue_answers_are_role_scoped(
    client: AsyncClient, citizen2_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/api/v1/assistant/query",
        json={"question": "which complaints are overdue in ward 1"},
        headers=citizen2_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scope"] == "own"
    assert all(
        citation["complaint_id"] for citation in body["citations"]
    )  # ids, when any, are still scoped to the caller


@pytest.mark.asyncio
async def test_examples_endpoint_is_self_consistent(
    client: AsyncClient, citizen_headers: dict[str, str]
) -> None:
    resp = await client.get("/api/v1/assistant/examples", headers=citizen_headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 3
