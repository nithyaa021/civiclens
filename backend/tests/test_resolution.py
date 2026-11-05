"""Before/after resolution verification and the citizen verdict workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO

import pytest
from bson import ObjectId
from httpx import AsyncClient
from PIL import Image

from app.ai.resolution import FEATURE_NAMES, extract_features, verify_fix
from app.core.config import get_settings
from app.data.corpus import generate_resolution_pairs
from tests.helpers import complaint_payload


def _png(color: tuple[int, int, int] = (120, 120, 120)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (96, 96), color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(scope="module")
def image_pair() -> tuple[bytes, bytes]:
    before, after, label, _pair_id = generate_resolution_pairs(count=4, seed=99)[0]
    assert label == 1
    return before, after


def test_feature_extraction_is_explainable(image_pair: tuple[bytes, bytes]) -> None:
    before, after = image_pair
    features = extract_features(before, after)
    assert set(features) == set(FEATURE_NAMES)
    assert -1.0 <= features["clip_sim"] <= 1.0
    assert -1.0 <= features["ssim"] <= 1.0
    assert all(isinstance(value, float) for value in features.values())


def test_verify_fix_returns_a_bounded_confidence(image_pair: tuple[bytes, bytes]) -> None:
    before, after = image_pair
    confidence, features, version = verify_fix(before, after)
    assert 0.0 <= confidence <= 1.0
    assert set(features) == set(FEATURE_NAMES)
    assert version


async def _file(client: AsyncClient, headers: dict[str, str]) -> dict:  # noqa: ANN003
    resp = await client.post(
        "/api/v1/complaints", json=complaint_payload(), headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _attach_before(client: AsyncClient, headers: dict[str, str], complaint_id: str) -> None:
    resp = await client.post(
        f"/api/v1/complaints/{complaint_id}/attachments",
        files={"file": ("before.png", _png((90, 90, 90)), "image/png")},
        data={"kind": "before"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_resolution_requires_a_before_photo(
    client: AsyncClient,
    citizen_headers: dict[str, str],
    officer_headers: dict[str, str],
) -> None:
    created = await _file(client, citizen_headers)
    resp = await client.post(
        f"/api/v1/complaints/{created['id']}/resolution",
        files={"file": ("after.png", _png(), "image/png")},
        headers=officer_headers,
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["details"]["reason"] == "before_photo_required"


@pytest.mark.asyncio
async def test_after_photo_is_verified_by_the_model(
    client: AsyncClient,
    citizen_headers: dict[str, str],
    officer_headers: dict[str, str],
) -> None:
    created = await _file(client, citizen_headers)
    await _attach_before(client, citizen_headers, created["id"])

    # Move to in_progress first (assigned -> in_progress is the legal route).
    await client.patch(
        f"/api/v1/complaints/{created['id']}/status",
        json={"status": "in_progress"},
        headers=officer_headers,
    )

    before, after, _, _ = generate_resolution_pairs(count=2, seed=99)[0]
    resp = await client.post(
        f"/api/v1/complaints/{created['id']}/resolution",
        files={"file": ("after.png", after, "image/png")},
        data={"note": "Pothole filled and compacted"},
        headers=officer_headers,
    )
    assert resp.status_code == 202, resp.text

    detail = await client.get(f"/api/v1/complaints/{created['id']}", headers=citizen_headers)
    assert detail.status_code == 200, detail.text
    verification = detail.json()["resolution"]["verification"]
    assert 0.0 <= verification["confidence"] <= 1.0
    assert set(verification["features"]) == set(FEATURE_NAMES)
    assert verification["model_version"]
    assert verification["passed"] is (
        verification["confidence"] >= get_settings().resolution_pass_threshold
    )


@pytest.mark.asyncio
async def test_citizen_confirms_and_disputes_only_after_verification(
    client: AsyncClient,
    citizen_headers: dict[str, str],
    citizen2_headers: dict[str, str],
    officer_headers: dict[str, str],
    db,
) -> None:
    created = await _file(client, citizen_headers)
    await _attach_before(client, citizen_headers, created["id"])

    # Not resolved yet -> confirm is a conflict.
    early = await client.post(
        f"/api/v1/complaints/{created['id']}/resolution/confirm",
        json={},
        headers=citizen_headers,
    )
    assert early.status_code == 409

    # Simulate the verified state produced by the worker (model already tested above).
    now = datetime.now(UTC)
    await db["complaints"].update_one(
        {"_id": ObjectId(created["id"])},
        {
            "$set": {
                "status": "resolved",
                "resolved_at": now,
                "resolution": {
                    "after_media_id": created["id"],
                    "officer_id": None,
                    "note": "filled",
                    "verification": {
                        "after_media_id": created["id"],
                        "confidence": 0.82,
                        "passed": True,
                        "features": {name: 0.0 for name in FEATURE_NAMES},
                        "model_version": "test-comparator-v1",
                        "note": None,
                        "verified_at": now,
                    },
                    "citizen_decision": None,
                    "decision_note": None,
                    "decided_at": None,
                    "created_at": now,
                },
            }
        },
    )

    stranger = await client.post(
        f"/api/v1/complaints/{created['id']}/resolution/confirm",
        json={"note": "looks fixed"},
        headers=citizen2_headers,
    )
    assert stranger.status_code == 403

    confirmed = await client.post(
        f"/api/v1/complaints/{created['id']}/resolution/confirm",
        json={"note": "verified on site"},
        headers=citizen_headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "closed"
    assert confirmed.json()["resolution"]["citizen_decision"] == "confirmed"
    assert confirmed.json()["resolution"]["decision_note"] == "verified on site"

    audit = await client.get(
        f"/api/v1/complaints/{created['id']}/audit", headers=citizen_headers
    )
    actions = [event["action"] for event in audit.json()["items"]]
    assert "resolution_confirmed" in actions


@pytest.mark.asyncio
async def test_dispute_reopens_the_complaint(
    client: AsyncClient, citizen_headers: dict[str, str], db
) -> None:
    created = await _file(client, citizen_headers)
    now = datetime.now(UTC)
    await db["complaints"].update_one(
        {"_id": ObjectId(created["id"])},
        {
            "$set": {
                "status": "resolved",
                "resolved_at": now,
                "resolution": {
                    "after_media_id": created["id"],
                    "officer_id": None,
                    "note": None,
                    "verification": {
                        "after_media_id": created["id"],
                        "confidence": 0.79,
                        "passed": True,
                        "features": {name: 0.0 for name in FEATURE_NAMES},
                        "model_version": "test-comparator-v1",
                        "note": None,
                        "verified_at": now,
                    },
                    "citizen_decision": None,
                    "decision_note": None,
                    "decided_at": None,
                    "created_at": now,
                },
            }
        },
    )
    resp = await client.post(
        f"/api/v1/complaints/{created['id']}/resolution/dispute",
        json={"note": "pothole is still there"},
        headers=citizen_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "in_progress"
    assert body["resolution"]["citizen_decision"] == "disputed"
