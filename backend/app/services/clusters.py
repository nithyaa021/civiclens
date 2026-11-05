"""Recurring-issue cluster computation and priority refresh (async API path).

The heavy lifting is done by the pure modules in :mod:`app.ai`; this service
handles the Mongo reads/writes and keeps the persisted ``clusters`` collection
and the ``cluster_id`` / ``priority`` fields on complaints in sync.

The same logic is available to the worker as
``civiclens.recompute_analytics`` (sync, pymongo); both use the identical pure
functions so a scheduled run and an on-demand call cannot disagree.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from bson import ObjectId
from fastapi.concurrency import run_in_threadpool
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.ai.clustering import cluster_complaints
from app.ai.priority import compute_priority
from app.core.config import Settings
from app.models.complaint import ComplaintSummary, RecurringCluster
from app.models.ward import GeoPoint
from app.services.wards import nearest_sensitive_km

OPEN_STATUSES = ("submitted", "assigned", "in_progress")


async def recompute(db: AsyncIOMotorDatabase, settings: Settings) -> dict[str, Any]:
    """Rebuild clusters and refresh stored priority scores.

    Returns a small summary (counts + timestamp) for the API/worker result.
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=settings.cluster_lookback_days)

    projection = {
        "category": 1,
        "location": 1,
        "created_at": 1,
        "status": 1,
        "ward": 1,
        "severity": 1,
        "votes": 1,
        "embedding": 1,
        "cluster_id": 1,
    }
    rows = [
        doc async for doc in db["complaints"].find({"created_at": {"$gte": cutoff}}, projection)
    ]
    embeddings = {str(row["_id"]): row["embedding"] for row in rows if row.get("embedding")}

    clusters = await run_in_threadpool(cluster_complaints, rows, embeddings, settings=settings)

    # Replace the derived collection atomically enough for readers: write the
    # new documents first, then drop the stale ones by id.
    new_ids = [cluster.pop("cluster_key") for cluster in clusters]
    if new_ids:
        await db["clusters"].delete_many({"_id": {"$nin": new_ids}})
    else:
        await db["clusters"].delete_many({})
    if clusters:
        for cluster, cluster_id in zip(clusters, new_ids, strict=True):
            cluster["_id"] = cluster_id
            await db["clusters"].replace_one({"_id": cluster_id}, cluster, upsert=True)

    member_of: dict[str, str] = {}
    cluster_sizes: dict[str, int] = {}
    for cluster_id, cluster in zip(new_ids, clusters, strict=True):
        for complaint_id in cluster["complaint_ids"]:
            member_of[complaint_id] = cluster_id
            cluster_sizes[complaint_id] = int(cluster["count"])

    # Keep cluster membership accurate for every row in the window (including
    # complaints that dropped out of any cluster on this run).
    for row in rows:
        complaint_id = str(row["_id"])
        desired = member_of.get(complaint_id)
        if row.get("cluster_id") != desired:
            await db["complaints"].update_one(
                {"_id": row["_id"]}, {"$set": {"cluster_id": desired}}
            )

    ward_docs = {doc["ward_no"]: doc async for doc in db["wards"].find()}
    refreshed = 0
    for row in rows:
        if row.get("status") not in OPEN_STATUSES:
            continue
        ward_doc = ward_docs.get(row.get("ward"))
        nearest = (
            nearest_sensitive_km(
                ward_doc, GeoPoint(coordinates=tuple(row["location"]["coordinates"]))
            )
            if ward_doc
            else None
        )
        priority = compute_priority(
            severity=int(row.get("severity", 3)),
            votes=int(row.get("votes", 0)),
            cluster_count=cluster_sizes.get(str(row["_id"]), 0),
            created_at=row["created_at"],
            resolved_at=None,
            now=now,
            nearest_sensitive_km=nearest,
            weights=settings.priority_weights,
            sensitive_radius_km=settings.priority_sensitive_radius_km,
            max_age_days=settings.priority_max_age_days,
        )
        await db["complaints"].update_one(
            {"_id": row["_id"]}, {"$set": {"priority": priority.model_dump()}}
        )
        refreshed += 1

    return {
        "complaints_scanned": len(rows),
        "priorities_refreshed": refreshed,
        "clusters": len(clusters),
        "computed_at": now.isoformat(),
    }


def serialize_cluster(doc: dict[str, Any]) -> RecurringCluster:
    """Convert a stored cluster document into :class:`RecurringCluster`."""
    return RecurringCluster(
        id=str(doc["_id"]),
        category=doc["category"],
        count=int(doc["count"]),
        open_count=int(doc["open_count"]),
        first_reported=doc["first_reported"],
        last_reported=doc["last_reported"],
        affected_area={
            "centroid": doc["centroid"],
            "radius_km": float(doc["radius_km"]),
            "bbox": tuple(tuple(point) for point in doc["bbox"]),
        },
        dominant_ward=doc.get("dominant_ward"),
        complaint_ids=[str(cid) for cid in doc["complaint_ids"]],
        computed_at=doc["computed_at"],
    )


async def list_clusters(
    db: AsyncIOMotorDatabase,
    *,
    category: str | None = None,
    ward: int | None = None,
    min_count: int = 1,
    limit: int = 50,
) -> list[RecurringCluster]:
    """Stored recurring-issue clusters, largest first."""
    query: dict[str, Any] = {"count": {"$gte": min_count}}
    if category is not None:
        query["category"] = category
    if ward is not None:
        query["dominant_ward"] = ward
    cursor = db["clusters"].find(query).sort("count", -1).limit(limit)
    return [serialize_cluster(doc) async for doc in cursor]


async def cluster_members(
    db: AsyncIOMotorDatabase, complaint_ids: list[str]
) -> list[ComplaintSummary]:
    """Hydrate stored complaint ids into summary cards (skips missing ids)."""
    from app.services.complaints import summarize

    oids = [ObjectId(cid) for cid in complaint_ids if ObjectId.is_valid(cid)]
    if not oids:
        return []
    docs = [doc async for doc in db["complaints"].find({"_id": {"$in": oids}})]
    order = {cid: index for index, cid in enumerate(complaint_ids)}
    docs.sort(key=lambda doc: order.get(str(doc["_id"]), 0))
    return [summarize(doc) for doc in docs]
