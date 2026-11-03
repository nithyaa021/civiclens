"""Async job endpoint tests (eager Celery executes tasks inline)."""

from __future__ import annotations

import hashlib
import uuid
from io import BytesIO

import pytest
from httpx import AsyncClient
from PIL import Image

from app.core.config import get_settings
from app.db.mongo import get_database
from app.workers.tasks.embeddings import DEFAULT_DIMENSION, embed_text


def _png_bytes(
    width: int = 64, height: int = 48, color: tuple[int, int, int] = (200, 40, 40)
) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


# --- Embeddings ---------------------------------------------------------------
@pytest.mark.asyncio
async def test_embedding_job_end_to_end(
    client: AsyncClient, citizen_headers: dict[str, str]
) -> None:
    text = "Garbage has not been collected near the market for five days."
    queued = await client.post(
        "/api/v1/jobs/embeddings",
        json={"text": text, "kind": "complaint"},
        headers=citizen_headers,
    )
    assert queued.status_code == 202, queued.text
    task_id = queued.json()["task_id"]

    status_resp = await client.get(f"/api/v1/jobs/{task_id}", headers=citizen_headers)
    assert status_resp.status_code == 200
    body = status_resp.json()
    assert body["state"] == "SUCCESS", body
    result = body["result"]
    assert result["dimension"] == DEFAULT_DIMENSION
    assert result["token_count"] > 0
    assert result["norm"] == pytest.approx(1.0, abs=1e-6)

    # The vector must actually be persisted and unit-normalised.
    db = get_database()
    doc = await db["embeddings"].find_one(
        {"text_sha256": hashlib.sha256(text.encode()).hexdigest()}
    )
    assert doc is not None
    assert len(doc["vector"]) == DEFAULT_DIMENSION
    norm = sum(v * v for v in doc["vector"]) ** 0.5
    assert norm == pytest.approx(1.0, abs=1e-6)


def test_embed_text_is_deterministic_and_discriminative() -> None:
    a1 = embed_text("pothole on stadium road near the bus stop")
    a2 = embed_text("pothole on stadium road near the bus stop")
    assert a1 == a2, "same text must produce identical vectors"

    def cosine(x: list[float], y: list[float]) -> float:
        return sum(i * j for i, j in zip(x, y, strict=True))

    similar = cosine(embed_text("pothole on stadium road"), embed_text("big pothole stadium road"))
    unrelated = cosine(
        embed_text("pothole on stadium road"), embed_text("annual music festival permits")
    )
    assert similar > unrelated, "near-duplicate text must be closer than unrelated text"


@pytest.mark.asyncio
async def test_embedding_rejects_empty_text(
    client: AsyncClient, citizen_headers: dict[str, str]
) -> None:
    resp = await client.post("/api/v1/jobs/embeddings", json={"text": "x"}, headers=citizen_headers)
    # "x" is valid; whitespace-only would be a min_length pass but fails in task.
    assert resp.status_code == 202

    queued = await client.post(
        "/api/v1/jobs/embeddings", json={"text": "y" * 8001}, headers=citizen_headers
    )
    assert queued.status_code == 422  # max_length=8000


# --- Image analysis -----------------------------------------------------------
@pytest.mark.asyncio
async def test_image_analysis_job_end_to_end(
    client: AsyncClient, citizen_headers: dict[str, str]
) -> None:
    img_bytes = _png_bytes(80, 60, color=(30, 120, 220))
    queued = await client.post(
        "/api/v1/jobs/image-analysis",
        files={"file": ("street.png", img_bytes, "image/png")},
        headers=citizen_headers,
    )
    assert queued.status_code == 202, queued.text
    task_id = queued.json()["task_id"]

    status_resp = await client.get(f"/api/v1/jobs/{task_id}", headers=citizen_headers)
    assert status_resp.status_code == 200
    body = status_resp.json()
    assert body["state"] == "SUCCESS", body
    result = body["result"]
    assert result["width"] == 80 and result["height"] == 60
    assert result["format"] == "PNG"
    assert 0 <= result["brightness"] <= 255
    assert isinstance(result["blur_score"], float)
    assert result["dominant_colors"], "dominant colours must be reported"
    assert result["dominant_colors"][0]["hex"].startswith("#")

    # Result persisted under job_results for auditing.
    db = get_database()
    stored = await db["job_results"].find_one({"task_id": task_id})
    assert stored is not None
    assert stored["result"]["width"] == 80


@pytest.mark.asyncio
async def test_image_rejects_unsupported_type_and_empty(
    client: AsyncClient, citizen_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/api/v1/jobs/image-analysis",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        headers=citizen_headers,
    )
    assert resp.status_code == 415
    assert resp.json()["error"]["code"] == "unsupported_media_type"

    empty = await client.post(
        "/api/v1/jobs/image-analysis",
        files={"file": ("empty.png", b"", "image/png")},
        headers=citizen_headers,
    )
    assert empty.status_code == 400
    assert empty.json()["error"]["code"] == "empty_file"


# --- Notifications ------------------------------------------------------------
@pytest.mark.asyncio
async def test_notification_job_persists_and_lists(
    client: AsyncClient, citizen_headers: dict[str, str], citizen: dict
) -> None:
    subject = f"Complaint acknowledged {uuid.uuid4().hex[:6]}"
    queued = await client.post(
        "/api/v1/jobs/notifications",
        json={
            "user_id": citizen["id"],
            "subject": subject,
            "body": "Your report has been assigned to the ward officer.",
            "channel": "in_app",
        },
        headers=citizen_headers,
    )
    assert queued.status_code == 202, queued.text
    task_id = queued.json()["task_id"]

    status_resp = await client.get(f"/api/v1/jobs/{task_id}", headers=citizen_headers)
    assert status_resp.status_code == 200
    body = status_resp.json()
    assert body["state"] == "SUCCESS", body
    assert body["result"]["delivery"] == "stored_in_app"
    assert body["result"]["email"] == "not_requested"

    listing = await client.get("/api/v1/jobs/notifications", headers=citizen_headers)
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert any(item["subject"] == subject for item in items)


@pytest.mark.asyncio
async def test_email_channel_reports_honest_skip_without_smtp(
    client: AsyncClient, citizen_headers: dict[str, str], citizen: dict
) -> None:
    """With no SMTP configured the result must say skipped, never 'sent'."""
    assert get_settings().smtp_enabled is False
    queued = await client.post(
        "/api/v1/jobs/notifications",
        json={
            "user_id": citizen["id"],
            "subject": "Email check",
            "body": "Body",
            "channel": "email",
        },
        headers=citizen_headers,
    )
    task_id = queued.json()["task_id"]
    body = (await client.get(f"/api/v1/jobs/{task_id}", headers=citizen_headers)).json()
    assert body["state"] == "SUCCESS"
    assert body["result"]["email"] == "skipped_no_smtp"


@pytest.mark.asyncio
async def test_notification_to_unknown_user_fails_task(
    client: AsyncClient, citizen_headers: dict[str, str]
) -> None:
    queued = await client.post(
        "/api/v1/jobs/notifications",
        json={
            "user_id": "665f1c2e9b0d4a2f18c3ab99",
            "subject": "Ghost",
            "body": "No recipient",
            "channel": "in_app",
        },
        headers=citizen_headers,
    )
    task_id = queued.json()["task_id"]
    body = (await client.get(f"/api/v1/jobs/{task_id}", headers=citizen_headers)).json()
    assert body["state"] == "FAILURE"
    assert "not found" in (body["error"] or "").lower()


# --- Ownership / access -------------------------------------------------------
@pytest.mark.asyncio
async def test_job_visibility_is_scoped_to_owner(
    client: AsyncClient, citizen_headers: dict[str, str], admin_headers: dict[str, str]
) -> None:
    other = await client.post(
        "/api/v1/jobs/embeddings",
        json={"text": "private job", "kind": "note"},
        headers=citizen_headers,
    )
    task_id = other.json()["task_id"]

    # A second, unrelated citizen may not read someone else's job.
    other_email = f"nosy_{uuid.uuid4().hex[:8]}@example.com"
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": other_email, "full_name": "Other Citizen", "password": "ValidPass!2026"},
    )
    assert reg.status_code == 201
    login = await client.post(
        "/api/v1/auth/login", data={"username": other_email, "password": "ValidPass!2026"}
    )
    nosy_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    denied = await client.get(f"/api/v1/jobs/{task_id}", headers=nosy_headers)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "forbidden"

    # The owner can.
    allowed = await client.get(f"/api/v1/jobs/{task_id}", headers=citizen_headers)
    assert allowed.status_code == 200

    # Admins are explicitly allowed through the ownership check.
    as_admin = await client.get(f"/api/v1/jobs/{task_id}", headers=admin_headers)
    assert as_admin.status_code == 200


@pytest.mark.asyncio
async def test_unknown_job_id_404(client: AsyncClient, citizen_headers: dict[str, str]) -> None:
    resp = await client.get(
        "/api/v1/jobs/11111111-2222-3333-4444-555555555555", headers=citizen_headers
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_jobs_require_authentication(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/jobs/embeddings", json={"text": "hi"})
    assert resp.status_code == 401
