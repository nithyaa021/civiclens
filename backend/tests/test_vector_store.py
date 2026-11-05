"""Qdrant similarity index: stable ids, filters, exclusion, deletion."""

from __future__ import annotations

import uuid

import pytest

from app.ai.embeddings import embed_texts
from app.ai.vector_store import (
    clear_collection,
    delete_complaint,
    get_client,
    search_similar,
    upsert_complaint,
)

COLLECTION = "test_similarity"
CENTER = (77.50, 12.905)
FAR = (77.60, 12.95)


@pytest.fixture(scope="module", autouse=True)
def _collection() -> None:  # noqa: ANN001
    clear_collection(COLLECTION)
    yield
    client = get_client()
    if client.collection_exists(COLLECTION):
        client.delete_collection(COLLECTION)


def _payload(category: str, ward: int, lng: float, lat: float, status: str = "submitted") -> dict:
    return {
        "category": category,
        "ward": ward,
        "status": status,
        "created_at": "2026-10-01T10:00:00+00:00",
        "location": {"lon": lng, "lat": lat},
    }


def _ids() -> tuple[str, str, str]:
    return (str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()))


def test_upsert_and_search_returns_complaint_ids() -> None:
    pothole_id, garbage_id, park_id = _ids()
    vectors = embed_texts(
        [
            "Deep pothole on the main road near the bus stop",
            "Garbage has not been collected near the market for a week",
            "Broken swings in the ward park",
        ]
    )
    upsert_complaint(pothole_id, vectors[0], _payload("roads", 1, *CENTER), collection=COLLECTION)
    upsert_complaint(
        garbage_id,
        vectors[1],
        _payload("waste_management", 3, 77.57, 12.90),
        collection=COLLECTION,
    )
    upsert_complaint(park_id, vectors[2], _payload("parks_trees", 2, *FAR), collection=COLLECTION)

    hits = search_similar(
        vectors[0],
        limit=3,
        min_score=0.55,
        category="roads",
        collection=COLLECTION,
    )
    assert hits, "the indexed pothole should be found"
    assert hits[0][0] == pothole_id
    assert hits[0][2]["complaint_id"] == pothole_id
    assert hits[0][1] == pytest.approx(1.0, abs=1e-3)


def test_search_excludes_the_query_complaint() -> None:
    fresh = str(uuid.uuid4())
    vector = embed_texts(["Pothole filled with rainwater in the middle of the lane"])[0]
    upsert_complaint(fresh, vector, _payload("roads", 1, *CENTER), collection=COLLECTION)

    without_exclusion = search_similar(
        vector,
        limit=5,
        min_score=0.5,
        category="roads",
        exclude_id="does-not-matter",
        collection=COLLECTION,
    )
    assert any(hit[0] == fresh for hit in without_exclusion)

    excluded = search_similar(
        vector,
        limit=5,
        min_score=0.5,
        category="roads",
        exclude_id=fresh,
        collection=COLLECTION,
    )
    assert all(hit[0] != fresh for hit in excluded)


def test_geo_radius_filter() -> None:
    near_id, far_id = str(uuid.uuid4()), str(uuid.uuid4())
    vector = embed_texts(["Street lights are not working on the lane"])[0]
    upsert_complaint(near_id, vector, _payload("streetlight", 1, *CENTER), collection=COLLECTION)
    upsert_complaint(
        far_id, vector, _payload("streetlight", 2, 77.60, 12.95), collection=COLLECTION
    )

    hits = search_similar(
        vector,
        limit=5,
        min_score=0.5,
        category="streetlight",
        center_lng=CENTER[0],
        center_lat=CENTER[1],
        radius_km=1.0,
        collection=COLLECTION,
    )
    ids = {hit[0] for hit in hits}
    assert near_id in ids
    assert far_id not in ids


def test_delete_removes_the_point() -> None:
    complaint_id = str(uuid.uuid4())
    vector = embed_texts(["Water supply has been cut for five days"])[0]
    upsert_complaint(
        complaint_id, vector, _payload("water_supply", 1, *CENTER), collection=COLLECTION
    )
    delete_complaint(complaint_id, collection=COLLECTION)
    hits = search_similar(
        vector, limit=5, min_score=0.5, category="water_supply", collection=COLLECTION
    )
    assert all(hit[0] != complaint_id for hit in hits)
