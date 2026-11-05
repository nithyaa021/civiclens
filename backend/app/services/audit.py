"""Audit trail helpers.

Every meaningful state change (creation, assignment, status transitions,
escalations, resolution decisions) is appended to the ``audit_events``
collection with the acting user and structured details.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.complaint import AuditEvent, AuditPage


async def record_event(
    db: AsyncIOMotorDatabase,
    *,
    action: str,
    complaint_id: str | None = None,
    actor_id: str | None = None,
    actor_role: str | None = None,
    details: dict[str, Any] | None = None,
) -> str:
    """Append one immutable audit entry; returns its id."""
    document = {
        "action": action,
        "complaint_id": complaint_id,
        "actor_id": actor_id,
        "actor_role": actor_role,
        "details": details or {},
        "at": datetime.now(UTC),
    }
    result = await db["audit_events"].insert_one(document)
    return str(result.inserted_id)


def _serialize(doc: dict[str, Any]) -> AuditEvent:
    return AuditEvent(
        id=str(doc["_id"]),
        action=doc["action"],
        complaint_id=doc.get("complaint_id"),
        actor_id=doc.get("actor_id"),
        actor_role=doc.get("actor_role"),
        details=doc.get("details") or {},
        at=doc["at"],
    )


async def list_for_complaint(
    db: AsyncIOMotorDatabase, complaint_id: str, *, limit: int = 200
) -> AuditPage:
    """Audit entries for one complaint, oldest first."""
    cursor = db["audit_events"].find({"complaint_id": complaint_id}).sort("at", 1).limit(limit)
    items = [_serialize(doc) async for doc in cursor]
    return AuditPage(items=items, total=len(items))


async def complaint_exists(db: AsyncIOMotorDatabase, complaint_id: str) -> bool:
    if not ObjectId.is_valid(complaint_id):
        return False
    return await db["complaints"].count_documents({"_id": ObjectId(complaint_id)}, limit=1) > 0
