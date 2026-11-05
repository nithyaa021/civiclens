"""Ward geography services: lookup, point-in-ward resolution, sensitive sites."""

from __future__ import annotations

import math
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.ai.clustering import haversine_km
from app.core.errors import ApiError, NotFoundError
from app.models.ward import GeoPoint, SensitiveLocation, WardPublic


def ward_public(doc: dict[str, Any], *, complaint_count: int = 0) -> WardPublic:
    """Serialise a ward document (centroid derived from the polygon ring)."""
    ring = doc["geometry"]["coordinates"][0]
    lngs = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    centroid = GeoPoint(coordinates=((min(lngs) + max(lngs)) / 2, (min(lats) + max(lats)) / 2))
    return WardPublic(
        ward_no=doc["ward_no"],
        name=doc["name"],
        zone=doc["zone"],
        centroid=centroid,
        sensitive_locations=[
            SensitiveLocation(**item) for item in doc.get("sensitive_locations", [])
        ],
        complaint_count=complaint_count,
    )


async def list_wards(db: AsyncIOMotorDatabase) -> list[WardPublic]:
    """All wards with their open-complaint counts."""
    counts: dict[int, int] = {}
    open_statuses = ["submitted", "assigned", "in_progress"]
    pipeline = [
        {"$match": {"status": {"$in": open_statuses}, "ward": {"$ne": None}}},
        {"$group": {"_id": "$ward", "n": {"$sum": 1}}},
    ]
    async for row in db["complaints"].aggregate(pipeline):
        counts[int(row["_id"])] = int(row["n"])

    wards: list[WardPublic] = []
    async for doc in db["wards"].find().sort("ward_no", 1):
        wards.append(ward_public(doc, complaint_count=counts.get(doc["ward_no"], 0)))
    return wards


async def resolve_ward(db: AsyncIOMotorDatabase, point: GeoPoint) -> dict[str, Any] | None:
    """Return the ward polygon containing ``point`` (2dsphere intersection)."""
    return await db["wards"].find_one(
        {
            "geometry": {
                "$geoIntersects": {
                    "$geometry": {"type": "Point", "coordinates": list(point.coordinates)}
                }
            }
        }
    )


async def resolve_ward_or_raise(db: AsyncIOMotorDatabase, point: GeoPoint) -> dict[str, Any]:
    """Like :func:`resolve_ward` but raises 400 when outside every ward."""
    ward = await resolve_ward(db, point)
    if ward is None:
        raise ApiError(
            400,
            "outside_service_area",
            "That location is outside every configured ward. "
            "Move the pin inside the service area and try again.",
            details={"coordinates": list(point.coordinates)},
        )
    return ward


def nearest_sensitive_km(ward_doc: dict[str, Any], point: GeoPoint) -> float | None:
    """Distance to the nearest school/hospital in the ward (None when none)."""
    locations = ward_doc.get("sensitive_locations") or []
    if not locations:
        return None
    distances = [
        haversine_km(
            point.lng,
            point.lat,
            item["location"]["coordinates"][0],
            item["location"]["coordinates"][1],
        )
        for item in locations
    ]
    return round(min(distances), 4)


async def get_ward_by_no(db: AsyncIOMotorDatabase, ward_no: int) -> dict[str, Any]:
    doc = await db["wards"].find_one({"ward_no": ward_no})
    if doc is None:
        raise NotFoundError("Ward", str(ward_no))
    return doc


def ward_distance_km(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Centroid distance between two ward documents (used by forecasting UIs)."""

    def centroid(ward: dict[str, Any]) -> tuple[float, float]:
        ring = ward["geometry"]["coordinates"][0]
        lngs = [p[0] for p in ring]
        lats = [p[1] for p in ring]
        return (sum(lngs) / len(lngs), sum(lats) / len(lats))

    ca, cb = centroid(a), centroid(b)
    return haversine_km(ca[0], ca[1], cb[0], cb[1])


def area_of_polygon_km2(ring: list[tuple[float, float]]) -> float:
    """Shoelace area in km^2 (approximate for small polygons)."""
    if len(ring) < 4:
        return 0.0
    # Project to km around the mean latitude.
    mean_lat = sum(p[1] for p in ring) / len(ring)
    km_per_deg_lat = 110.574
    km_per_deg_lng = 111.320 * math.cos(math.radians(mean_lat))
    xs = [p[0] * km_per_deg_lng for p in ring]
    ys = [p[1] * km_per_deg_lat for p in ring]
    area = 0.0
    for i in range(len(ring) - 1):
        area += xs[i] * ys[i + 1] - xs[i + 1] * ys[i]
    return abs(area) / 2.0
