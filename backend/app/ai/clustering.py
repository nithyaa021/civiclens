"""Geospatial + semantic complaint clustering (DBSCAN).

Distance combines physical proximity and embedding similarity:

    d(i, j) = geo_weight * (haversine_km(i, j) / geo_scale_km)
            + semantic_weight * (1 - cosine(i, j))

Clustering runs per category so a tight group of potholes never merges with
a tight group of garbage dumps.  ``sklearn.DBSCAN`` with a precomputed
distance matrix handles the small batches we deal with (hundreds of
complaints per category at most).
"""

from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime
from typing import Any

import numpy as np

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger("civiclens.ai.clustering")


def haversine_km(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    """Great-circle distance in kilometres."""
    radius_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius_km * math.asin(math.sqrt(a))


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def pairwise_distance_matrix(
    coords: list[tuple[float, float]],
    vectors: list[list[float]],
    settings: Settings,
) -> np.ndarray:
    """Symmetric matrix of combined geo+semantic distances (diagonal 0)."""
    n = len(coords)
    matrix = np.zeros((n, n), dtype=float)
    for i in range(n):
        for j in range(i + 1, n):
            geo = haversine_km(coords[i][0], coords[i][1], coords[j][0], coords[j][1])
            semantic = 1.0 - _cosine(vectors[i], vectors[j])
            distance = (
                settings.cluster_geo_weight * (geo / settings.cluster_geo_scale_km)
                + settings.cluster_semantic_weight * semantic
            )
            matrix[i, j] = matrix[j, i] = distance
    return matrix


def cluster_complaints(
    rows: list[dict[str, Any]],
    embeddings: dict[str, list[float]],
    *,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Cluster ``rows`` (complaint documents) into recurring-issue groups.

    Each returned dict is ready to persist to the ``clusters`` collection.
    Only groups with at least ``cluster_min_samples`` members produce a
    cluster; singletons and noise are skipped.
    """
    from sklearn.cluster import DBSCAN

    settings = settings or get_settings()
    computed_at = datetime.now(UTC)

    by_category: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        cid = str(row["_id"])
        if cid not in embeddings:
            continue
        by_category.setdefault(str(row["category"]), []).append(row)

    clusters: list[dict[str, Any]] = []
    for category, members in sorted(by_category.items()):
        if len(members) < settings.cluster_min_samples:
            continue
        coords = [
            (float(m["location"]["coordinates"][0]), float(m["location"]["coordinates"][1]))
            for m in members
        ]
        vectors = [embeddings[str(m["_id"])] for m in members]
        distances = pairwise_distance_matrix(coords, vectors, settings)
        labels = DBSCAN(
            eps=settings.cluster_eps,
            min_samples=settings.cluster_min_samples,
            metric="precomputed",
        ).fit_predict(distances)

        for label in sorted(set(int(item) for item in labels if item != -1)):
            member_idx = [i for i, value in enumerate(labels) if value == label]
            member_docs = [members[i] for i in member_idx]
            clusters.append(
                _build_cluster(category, member_docs, [coords[i] for i in member_idx], computed_at)
            )
    return clusters


def _build_cluster(
    category: str,
    docs: list[dict[str, Any]],
    coords: list[tuple[float, float]],
    computed_at: datetime,
) -> dict[str, Any]:
    lngs = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    centroid = (sum(lngs) / len(lngs), sum(lats) / len(lats))
    radius = max(haversine_km(centroid[0], centroid[1], lng, lat) for lng, lat in coords)
    created = [doc["created_at"] for doc in docs]
    open_statuses = {"submitted", "assigned", "in_progress"}
    wards = [doc.get("ward") for doc in docs if doc.get("ward") is not None]
    dominant_ward = max(set(wards), key=wards.count) if wards else None
    ids = [str(doc["_id"]) for doc in docs]
    # Membership fingerprint keeps cluster ids stable between runs while
    # guaranteeing two same-day, same-ward clusters never collide.
    fingerprint = hashlib.sha1("|".join(sorted(ids)).encode("utf-8")).hexdigest()[:10]

    return {
        "cluster_key": (
            f"{category}:{dominant_ward or 'x'}:{min(created).date().isoformat()}:{fingerprint}"
        ),
        "category": category,
        "count": len(docs),
        "open_count": sum(1 for doc in docs if doc.get("status") in open_statuses),
        "first_reported": min(created),
        "last_reported": max(created),
        "centroid": {"type": "Point", "coordinates": [centroid[0], centroid[1]]},
        "radius_km": round(radius, 4),
        "bbox": [
            [min(lngs), min(lats)],
            [max(lngs), max(lats)],
        ],
        "dominant_ward": dominant_ward,
        "complaint_ids": ids,
        "computed_at": computed_at,
    }
