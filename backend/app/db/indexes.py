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
    ],
    "embeddings": [
        ([("source_id", ASCENDING), ("kind", ASCENDING)], {"name": "embedding_source_kind"}),
    ],
}


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    """Create every index the application relies on."""
    for collection, specs in INDEX_SPECS.items():
        coll = db[collection]
        for keys, options in specs:
            await coll.create_index(keys, **options)
    logger.info("indexes_ensured", database=db.name, collections=sorted(INDEX_SPECS))
