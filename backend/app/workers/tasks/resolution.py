"""Resolution verification task: compare before/after photos for real.

Reads both images from the ``media`` collection, runs the CLIP + trained
comparator pipeline, stores the verification on the complaint, writes an audit
entry, and - when the fix passed - transitions the complaint to ``resolved``
and asks the reporter to confirm or dispute.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from celery.utils.log import get_task_logger

from app.workers.celery_app import celery_app

logger = get_task_logger(__name__)


@celery_app.task(name="jobs.verify_resolution", bind=True, acks_late=True)
def verify_resolution(
    self,
    complaint_id: str,
    after_media_id: str,
    requested_by: str | None = None,
) -> dict[str, Any]:
    """Verify an after-photo against the complaint's before-photo."""
    from app.ai.resolution import verify_fix
    from app.core.config import get_settings
    from app.db.sync_mongo import get_sync_database

    try:
        oid = ObjectId(complaint_id)
        after_oid = ObjectId(after_media_id)
    except InvalidId as exc:
        raise ValueError("Invalid complaint or media id") from exc

    db = get_sync_database()
    complaint = db["complaints"].find_one({"_id": oid})
    if complaint is None:
        raise FileNotFoundError(f"Complaint {complaint_id} not found")

    before_ref = next(
        (a for a in complaint.get("attachments") or [] if a.get("kind") == "before"), None
    )
    if before_ref is None:
        raise ValueError("Complaint has no 'before' photo to compare against")

    before_media = db["media"].find_one({"_id": ObjectId(before_ref["id"])})
    after_media = db["media"].find_one({"_id": after_oid})
    if before_media is None:
        raise FileNotFoundError("Before photo media record missing")
    if after_media is None:
        raise FileNotFoundError("After photo media record missing")
    if after_media.get("complaint_id") not in (None, complaint_id):
        raise ValueError("After photo belongs to a different complaint")

    confidence, features, model_version = verify_fix(before_media["data"], after_media["data"])
    settings = get_settings()
    passed = confidence >= settings.resolution_pass_threshold
    now = datetime.now(UTC)
    verification = {
        "after_media_id": after_media_id,
        "confidence": confidence,
        "passed": passed,
        "features": features,
        "model_version": model_version,
        "note": None,
        "verified_at": now,
    }

    db["complaints"].update_one(
        {"_id": oid},
        {"$set": {"resolution.verification": verification, "updated_at": now}},
    )
    db["audit_events"].insert_one(
        {
            "action": "resolution_verified",
            "complaint_id": complaint_id,
            "actor_id": requested_by,
            "actor_role": "system",
            "details": {"confidence": confidence, "passed": passed, "model_version": model_version},
            "at": now,
        }
    )

    transitioned = False
    if passed:
        result = db["complaints"].update_one(
            {"_id": oid, "status": {"$in": ["assigned", "in_progress"]}},
            {"$set": {"status": "resolved", "resolved_at": now, "updated_at": now}},
        )
        transitioned = result.modified_count == 1
        if transitioned:
            db["audit_events"].insert_one(
                {
                    "action": "status_changed",
                    "complaint_id": complaint_id,
                    "actor_id": None,
                    "actor_role": "system",
                    "details": {
                        "from": "in_progress",
                        "to": "resolved",
                        "note": "auto-resolved: image verification passed",
                        "confidence": confidence,
                    },
                    "at": now,
                }
            )
        citizen_id = complaint.get("citizen_id")
        if citizen_id:
            from app.workers.tasks.notifications import send_notification

            send_notification.delay(
                user_id=citizen_id,
                subject="Resolution awaiting your confirmation",
                body=(
                    f"The fix for '{complaint['title']}' was submitted and passed image "
                    f"verification (confidence {confidence:.0%}). Confirm it or dispute it."
                ),
                channel="in_app",
                requested_by=requested_by,
            )
    else:
        officer_id = complaint.get("assigned_officer_id") or (
            complaint.get("resolution") or {}
        ).get("officer_id")
        if officer_id:
            from app.workers.tasks.notifications import send_notification

            send_notification.delay(
                user_id=officer_id,
                subject="Resolution verification failed",
                body=(
                    f"The after-photo for '{complaint['title']}' scored only "
                    f"{confidence:.0%} (threshold {settings.resolution_pass_threshold:.0%}). "
                    "Upload a clearer photo of the completed work."
                ),
                channel="in_app",
                requested_by=requested_by,
            )

    outcome = {
        "complaint_id": complaint_id,
        "confidence": confidence,
        "passed": passed,
        "transitioned_to_resolved": transitioned,
        "model_version": model_version,
        "features": features,
    }
    logger.info("resolution_verified task=%s %s", self.request.id, outcome)
    return outcome
