"""Enrichment task: language, translation, embedding and category suggestion.

Runs synchronously in the Celery worker with ``pymongo`` (same pattern as the
Phase-1 tasks).  The pipeline is all-or-nothing: MongoDB is only updated after
every step succeeded, and a failure marks the complaint ``failed`` so it can
be retried - never silently half-populated.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from celery.utils.log import get_task_logger

from app.workers.celery_app import celery_app

logger = get_task_logger(__name__)


@celery_app.task(name="jobs.enrich_complaint", bind=True, acks_late=True)
def enrich_complaint(self, complaint_id: str) -> dict[str, Any]:
    """Detect language, translate, embed and classify one complaint."""
    from app.ai.classifier import predict_category
    from app.ai.embeddings import embed_texts
    from app.ai.language import detect_language
    from app.ai.translation import translate_to_english
    from app.ai.vector_store import upsert_complaint
    from app.db.sync_mongo import get_sync_database

    try:
        oid = ObjectId(complaint_id)
    except InvalidId as exc:
        raise ValueError(f"Invalid complaint id {complaint_id!r}") from exc

    db = get_sync_database()
    doc = db["complaints"].find_one({"_id": oid})
    if doc is None:
        raise FileNotFoundError(f"Complaint {complaint_id} not found")

    db["complaints"].update_one({"_id": oid}, {"$set": {"enrichment": "running"}})
    try:
        text = f"{doc['title']}\n{doc['description']}"
        language = detect_language(text)

        english_translation: str | None = None
        if language.code != "en":
            title_en, body_en = translate_to_english(
                [doc["title"], doc["description"]], [language.code, language.code]
            )
            english_translation = f"{title_en}\n{body_en}".strip()

        # Embed the English text when available so cross-language near
        # duplicates land close together in the vector space.
        [vector] = embed_texts([english_translation or text])
        suggestion = predict_category(text)

        payload: dict[str, Any] = {
            "category": doc["category"],
            "ward": doc.get("ward"),
            "status": doc["status"],
            "created_at": doc["created_at"].isoformat(),
            "location": {
                "lon": doc["location"]["coordinates"][0],
                "lat": doc["location"]["coordinates"][1],
            },
        }
        upsert_complaint(complaint_id, vector, payload)

        update: dict[str, Any] = {
            "enrichment": "done",
            "language": language.model_dump(),
            "english_translation": english_translation,
            "category_ml": suggestion.model_dump() if suggestion else None,
            "embedding": vector,
            "updated_at": datetime.now(UTC),
        }
        db["complaints"].update_one({"_id": oid}, {"$set": update})
        result = {
            "complaint_id": complaint_id,
            "language": language.code,
            "language_method": language.method,
            "translated": english_translation is not None,
            "predicted_category": suggestion.predicted.value if suggestion else None,
            "category_confidence": suggestion.confidence if suggestion else None,
            "embedding_dim": len(vector),
        }
        logger.info("enrichment_done task=%s %s", self.request.id, result)
        return result
    except Exception:
        db["complaints"].update_one(
            {"_id": oid}, {"$set": {"enrichment": "failed", "updated_at": datetime.now(UTC)}}
        )
        logger.exception("enrichment_failed task=%s complaint_id=%s", self.request.id, complaint_id)
        raise
