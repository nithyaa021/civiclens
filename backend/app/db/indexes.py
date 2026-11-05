"""Index creation for all collections (idempotent, run at startup)."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING

from app.core.logging import get_logger

logger = get_logger("civiclens.db.indexes")

INDEX_SPECS: dict[str, list[tuple[list[tuple[str, int]], dict]]] = {
    "users": [
        ([("email", ASCENDING)], {"unique": True, "name": "uniq_user_email"}),
        ([("role", ASCENDING)], {"name": "user_role"}),
        ([("created_at", DESCENDING)], {"name": "user_created_at"}),
    ],
    "notifications": [
        ([("user_id", ASCENDING), ("created_at", DESCENDING)], {"name": "notification_user_time"}),
    ],
    "job_results": [
        ([("task_id", ASCENDING)], {"unique": True, "name": "uniq_job_task"}),
        ([("user_id", ASCENDING), ("created_at", DESCENDING)], {"name": "job_user_time"}),
    ],
    "media": [
        ([("owner_id", ASCENDING), ("created_at", DESCENDING)], {"name": "media_owner_time"}),
        ([("complaint_id", ASCENDING)], {"name": "media_complaint"}),
    ],
    "embeddings": [
        ([("source_id", ASCENDING), ("kind", ASCENDING)], {"name": "embedding_source_kind"}),
    ],
    "wards": [
        ([("ward_no", ASCENDING)], {"unique": True, "name": "uniq_ward_no"}),
        ([("geometry", "2dsphere")], {"name": "ward_geometry"}),
        ([("sensitive_locations.location", "2dsphere")], {"name": "ward_sensitive_geo"}),
    ],
    "complaints": [
        ([("location", "2dsphere")], {"name": "complaint_location_geo"}),
        ([("title", "text"), ("description", "text")], {
            "name": "complaint_text_v2",
            # Complaints carry a structured `language` object, so Mongo must not
            # treat that field as the text-index language override.
            "language_override": "text_language",
            "default_language": "none",
        }),
        ([("status", ASCENDING), ("created_at", DESCENDING)], {"name": "complaint_status_time"}),
        ([("ward", ASCENDING), ("status", ASCENDING)], {"name": "complaint_ward_status"}),
        (
            [("category", ASCENDING), ("created_at", DESCENDING)],
            {"name": "complaint_category_time"},
        ),
        (
            [("citizen_id", ASCENDING), ("created_at", DESCENDING)],
            {"name": "complaint_citizen_time"},
        ),
        ([("assigned_officer_id", ASCENDING)], {"name": "complaint_officer"}),
        ([("priority.score", DESCENDING)], {"name": "complaint_priority"}),
        ([("sla.due_at", ASCENDING)], {"name": "complaint_sla_due"}),
        ([("cluster_id", ASCENDING)], {"name": "complaint_cluster"}),
        ([("duplicate_of", ASCENDING)], {"name": "complaint_duplicate_of"}),
    ],
    "clusters": [
        ([("category", ASCENDING), ("count", DESCENDING)], {"name": "cluster_category_count"}),
        ([("dominant_ward", ASCENDING), ("count", DESCENDING)], {"name": "cluster_ward_count"}),
        ([("last_reported", DESCENDING)], {"name": "cluster_last_reported"}),
    ],
    "audit_events": [
        ([("complaint_id", ASCENDING), ("at", ASCENDING)], {"name": "audit_complaint_time"}),
        ([("at", DESCENDING)], {"name": "audit_time"}),
        ([("action", ASCENDING), ("at", DESCENDING)], {"name": "audit_action_time"}),
    ],
}


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    """Create every index the application relies on."""
    # Phase-1 created a text index without a language override; it conflicts
    # with the structured `language` field on complaints, so replace it.
    try:
        existing = await db["complaints"].index_information()
        if "complaint_text" in existing:
            await db["complaints"].drop_index("complaint_text")
            logger.info("legacy_index_dropped", index="complaint_text")
    except Exception:  # noqa: BLE001 - collection/index may not exist yet
        logger.debug("legacy_index_check_skipped")
    for collection, specs in INDEX_SPECS.items():
        coll = db[collection]
        for keys, options in specs:
            await coll.create_index(keys, **options)
    logger.info("indexes_ensured", database=db.name, collections=sorted(INDEX_SPECS))
