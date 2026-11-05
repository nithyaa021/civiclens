"""Qdrant vector index for complaint similarity search.

Local development uses Qdrant's embedded mode (an on-disk index at
``settings.qdrant_path``); docker-compose points ``QDRANT_URL`` at a real
Qdrant server.  All operations are synchronous - async callers use
``run_in_threadpool``.
"""

from __future__ import annotations

import contextlib
import threading
import uuid
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("civiclens.ai.vector_store")

COMPLAINTS_COLLECTION = "complaints"

_client: Any = None
_client_lock = threading.Lock()
_collections_ready: set[str] = set()


def get_client() -> Any:
    """Return (creating on first call) the shared Qdrant client."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                from qdrant_client import QdrantClient

                settings = get_settings()
                if settings.qdrant_url:
                    _client = QdrantClient(
                        url=settings.qdrant_url,
                        api_key=settings.qdrant_api_key or None,
                        timeout=10,
                    )
                    mode = f"server {settings.qdrant_url}"
                else:
                    _client = QdrantClient(path=settings.qdrant_path)
                    mode = f"embedded {settings.qdrant_path}"
                logger.info("qdrant_client_ready", mode=mode)
    return _client


def ensure_collection(name: str = COMPLAINTS_COLLECTION) -> None:
    """Create the collection and payload indexes when they do not exist."""
    from qdrant_client import models

    settings = get_settings()
    client = get_client()
    with _client_lock:
        if name in _collections_ready:
            return
        if not client.collection_exists(name):
            client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(
                    size=settings.embedding_dim, distance=models.Distance.COSINE
                ),
            )
            logger.info("qdrant_collection_created", collection=name)
        # Payload indexes enable filtered search (category/ward/status) and
        # geo-radius constraints on top of the ANN query.
        for field, schema in (
            ("category", models.PayloadSchemaType.KEYWORD),
            ("ward", models.PayloadSchemaType.INTEGER),
            ("status", models.PayloadSchemaType.KEYWORD),
            ("location", models.PayloadSchemaType.GEO),
        ):
            with contextlib.suppress(Exception):
                client.create_payload_index(
                    collection_name=name, field_name=field, field_schema=schema
                )
        _collections_ready.add(name)


def _point_id(complaint_id: str) -> str:
    """Stable UUID for a Mongo complaint id (Qdrant accepts UUID/uint only)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"civiclens:complaint:{complaint_id}"))


def clear_collection(name: str = COMPLAINTS_COLLECTION) -> None:
    """Drop and recreate the collection (used by the seed script's --reset)."""
    client = get_client()
    if client.collection_exists(name):
        client.delete_collection(name)
    with _client_lock:
        _collections_ready.discard(name)
    ensure_collection(name)


def upsert_complaint(
    complaint_id: str,
    vector: list[float],
    payload: dict[str, Any],
    *,
    collection: str = COMPLAINTS_COLLECTION,
) -> None:
    """Insert or replace the embedding point for one complaint."""
    from qdrant_client import models

    ensure_collection(collection)
    get_client().upsert(
        collection_name=collection,
        points=[
            models.PointStruct(
                id=_point_id(complaint_id),
                vector=vector,
                payload={**payload, "complaint_id": complaint_id},
            )
        ],
        wait=True,
    )


def delete_complaint(complaint_id: str, *, collection: str = COMPLAINTS_COLLECTION) -> None:
    """Remove a complaint's point (used when a record is purged)."""
    from qdrant_client import models

    ensure_collection(collection)
    get_client().delete(
        collection_name=collection,
        points_selector=models.PointIdsList(points=[_point_id(complaint_id)]),
        wait=True,
    )


def search_similar(
    vector: list[float],
    *,
    limit: int,
    min_score: float,
    category: str | None = None,
    center_lng: float | None = None,
    center_lat: float | None = None,
    radius_km: float | None = None,
    exclude_id: str | None = None,
    collection: str = COMPLAINTS_COLLECTION,
) -> list[tuple[str, float, dict[str, Any]]]:
    """Cosine ANN search with optional category and geo-radius filters.

    Returns ``(complaint_id, score, payload)`` tuples with ``score >= min_score``.
    """
    from qdrant_client import models

    ensure_collection(collection)

    conditions: list[models.Condition] = []
    must_not: list[models.Condition] = []
    if category is not None:
        conditions.append(
            models.FieldCondition(key="category", match=models.MatchValue(value=category))
        )
    if center_lng is not None and center_lat is not None and radius_km is not None:
        conditions.append(
            models.FieldCondition(
                key="location",
                geo_radius=models.GeoRadius(
                    center=models.GeoPoint(lon=center_lng, lat=center_lat),
                    radius=radius_km * 1000.0,
                ),
            )
        )
    if exclude_id is not None:
        # IDs in the collection are UUIDv5 ids, so exclusion must be expressed as
        # a payload filter rather than a point-id filter.
        must_not.append(
            models.FieldCondition(
                key="complaint_id", match=models.MatchValue(value=exclude_id)
            )
        )

    query_filter = (
        models.Filter(
            must=conditions or None,
            must_not=must_not or None,
        )
        if conditions or must_not
        else None
    )
    hits = (
        get_client()
        .query_points(
            collection_name=collection,
            query=vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
            score_threshold=min_score,
        )
        .points
    )
    results: list[tuple[str, float, dict[str, Any]]] = []
    for hit in hits:
        payload = dict(hit.payload or {})
        complaint_id = str(payload.get("complaint_id") or "")
        if not complaint_id:
            continue
        results.append((complaint_id, float(hit.score), payload))
    return results
