"""Scheduled maintenance tasks (Celery beat).

- ``civiclens.sla_check``       - flags SLA breaches and escalates complaints
  up the configured ladder with notifications and an audit trail.
- ``civiclens.recompute_analytics`` - rebuilds recurring-issue clusters and
  refreshes stored priority scores from the latest embeddings.

Both run synchronously with ``pymongo`` (worker pattern from Phase 1) and
share the pure computation modules with the async API path.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from celery.utils.log import get_task_logger

from app.workers.celery_app import celery_app

logger = get_task_logger(__name__)

OPEN_STATUSES = ["submitted", "assigned", "in_progress"]


@celery_app.task(name="civiclens.sla_check", bind=True, acks_late=True)
def sla_check(self) -> dict[str, Any]:
    """Escalate every open complaint whose SLA clock has expired.

    Escalation spacing: the first breach escalates immediately; further
    rungs are reached only after another full ``target_hours`` has elapsed,
    so a complaint does not jump to the top of the ladder within minutes.
    """
    from app.core.config import get_settings
    from app.db.sync_mongo import get_sync_database

    settings = get_settings()
    db = get_sync_database()
    now = datetime.now(UTC)
    ladder = settings.escalation_ladder

    checked = 0
    escalated = 0
    cursor = db["complaints"].find({"status": {"$in": OPEN_STATUSES}, "sla.due_at": {"$lte": now}})
    for doc in cursor:
        checked += 1
        sla = doc.get("sla") or {}
        level = int(sla.get("escalation_level", 0))
        if level >= len(ladder):
            continue
        last_breach = sla.get("last_breach_at")
        target_hours = int(sla.get("target_hours", settings.sla_default_target_hours))
        if last_breach is not None and now - last_breach < timedelta(hours=target_hours):
            continue

        rung = ladder[level]
        new_level = level + 1
        due_at = sla["due_at"]
        breached_by_hours = round((now - due_at).total_seconds() / 3600.0, 2)
        first_breach = sla.get("escalated_at") is None

        set_fields: dict[str, Any] = {
            "sla.breached": True,
            "sla.breach_count": int(sla.get("breach_count", 0)) + 1,
            "sla.escalation_level": new_level,
            "sla.escalation_rung": rung,
            "sla.last_breach_at": now,
            "updated_at": now,
        }
        if first_breach:
            set_fields["sla.escalated_at"] = now
        if rung == ladder[-1]:
            set_fields["critical"] = True

        result = db["complaints"].update_one(
            {"_id": doc["_id"], "sla.escalation_level": level},
            {"$set": set_fields},
        )
        if result.modified_count != 1:
            continue  # concurrent escalation won the race
        escalated += 1

        db["audit_events"].insert_one(
            {
                "action": "sla_breached",
                "complaint_id": str(doc["_id"]),
                "actor_id": None,
                "actor_role": "system",
                "details": {
                    "rung": rung,
                    "level": new_level,
                    "target_hours": target_hours,
                    "due_at": due_at.isoformat(),
                    "breached_by_hours": breached_by_hours,
                },
                "at": now,
            }
        )

        recipients: set[str] = set()
        if doc.get("assigned_officer_id"):
            recipients.add(doc["assigned_officer_id"])
        admin_ids = [
            str(a["_id"])
            for a in db["users"].find({"role": "admin", "status": "active"}, {"_id": 1})
        ]
        recipients.update(admin_ids)

        from app.workers.tasks.notifications import send_notification

        subject = (
            f"CRITICAL: complaint escalated to {rung}"
            if rung == ladder[-1]
            else f"SLA breach: escalated to {rung}"
        )
        body = (
            f"'{doc['title']}' (Ward {doc.get('ward')}) passed its {target_hours}h SLA "
            f"and is now escalated to {rung} ({breached_by_hours:.1f}h overdue)."
        )
        for user_id in recipients:
            send_notification.delay(
                user_id=user_id,
                subject=subject,
                body=body,
                channel="in_app",
                requested_by=None,
            )
        if doc.get("citizen_id"):
            send_notification.delay(
                user_id=doc["citizen_id"],
                subject="Your report was escalated",
                body=(
                    f"'{doc['title']}' missed its response deadline and has been escalated "
                    f"to the {rung} level for action."
                ),
                channel="in_app",
                requested_by=None,
            )

    outcome = {"checked": checked, "escalated": escalated, "at": now.isoformat()}
    logger.info("sla_check_done task=%s %s", self.request.id, outcome)
    return outcome


@celery_app.task(name="civiclens.recompute_analytics", bind=True, acks_late=True)
def recompute_analytics(self) -> dict[str, Any]:
    """Rebuild clusters and refresh priority scores (pure functions + pymongo)."""
    from app.ai.clustering import cluster_complaints
    from app.ai.priority import compute_priority
    from app.core.config import get_settings
    from app.db.sync_mongo import get_sync_database
    from app.models.ward import GeoPoint
    from app.services.wards import nearest_sensitive_km

    settings = get_settings()
    db = get_sync_database()
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=settings.cluster_lookback_days)

    rows = list(
        db["complaints"].find(
            {"created_at": {"$gte": cutoff}},
            {
                "category": 1,
                "location": 1,
                "created_at": 1,
                "status": 1,
                "ward": 1,
                "severity": 1,
                "votes": 1,
                "embedding": 1,
            },
        )
    )
    embeddings = {str(r["_id"]): r["embedding"] for r in rows if r.get("embedding")}
    clusters = cluster_complaints(rows, embeddings, settings=settings)

    db["clusters"].delete_many({})
    if clusters:
        for cluster in clusters:
            cluster["_id"] = cluster.pop("cluster_key")
        db["clusters"].insert_many(clusters)

    member_of: dict[str, str] = {}
    counts: dict[str, int] = {}
    for cluster in clusters:
        for cid in cluster["complaint_ids"]:
            member_of[cid] = cluster["_id"]
            counts[cid] = cluster["count"]

    # Refresh stored cluster ids across the lookback window.
    for row in rows:
        cid = str(row["_id"])
        db["complaints"].update_one(
            {"_id": row["_id"]},
            {"$set": {"cluster_id": member_of.get(cid)}},
        )

    # Priority refresh for open complaints (cluster density may have changed).
    ward_docs = {w["ward_no"]: w for w in db["wards"].find()}
    refreshed = 0
    for row in rows:
        if row.get("status") not in OPEN_STATUSES:
            continue
        ward_doc = ward_docs.get(row.get("ward"))
        if ward_doc:
            point = GeoPoint(coordinates=tuple(row["location"]["coordinates"]))
            nearest = nearest_sensitive_km(ward_doc, point)
        else:
            nearest = None
        priority = compute_priority(
            severity=int(row.get("severity", 3)),
            votes=int(row.get("votes", 0)),
            cluster_count=counts.get(str(row["_id"]), 0),
            created_at=row["created_at"],
            resolved_at=None,
            now=now,
            nearest_sensitive_km=nearest,
            weights=settings.priority_weights,
            sensitive_radius_km=settings.priority_sensitive_radius_km,
            max_age_days=settings.priority_max_age_days,
        )
        db["complaints"].update_one(
            {"_id": row["_id"]}, {"$set": {"priority": priority.model_dump()}}
        )
        refreshed += 1

    outcome = {
        "complaints_scored": len(rows),
        "priorities_refreshed": refreshed,
        "clusters": len(clusters),
        "at": now.isoformat(),
    }
    logger.info("analytics_recomputed task=%s %s", self.request.id, outcome)
    return outcome
