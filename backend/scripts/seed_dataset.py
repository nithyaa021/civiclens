"""Seed the labeled benchmark corpus into MongoDB and Qdrant.

    python scripts/seed_dataset.py            # seed (keeps existing data)
    python scripts/seed_dataset.py --reset    # wipe domain collections first

What is created:

* 15 wards with polygons and sensitive sites;
* an admin, one ward officer per ward and five citizens;
* ~1,700 complaints over 120 days, with multilingual duplicates, stored
  embeddings, initial priority scores and SLA clocks;
* Qdrant points with category/ward/status/geo payloads for similarity search;
* creation audit entries.

Passwords are printed at the end (development-only accounts).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.ai.embeddings import embed_texts  # noqa: E402
from app.ai.priority import compute_priority  # noqa: E402
from app.ai.vector_store import clear_collection, ensure_collection, upsert_complaint  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.data.corpus import ComplaintSeed, generate_complaints, generate_wards  # noqa: E402
from app.db.sync_mongo import get_sync_database  # noqa: E402
from app.models.complaint import ComplaintStatus, EnrichmentStatus, SlaState  # noqa: E402
from app.services.wards import nearest_sensitive_km  # noqa: E402

OFFICER_PASSWORD = "Officer#12345"
CITIZEN_PASSWORD = "Citizen#12345"
ADMIN_PASSWORD = "Admin#12345"

DOMAIN_COLLECTIONS = [
    "complaints",
    "clusters",
    "wards",
    "audit_events",
    "media",
    "notifications",
    "job_results",
    "embeddings",
    "complaint_notes",
]


def english_translation_for(seed: ComplaintSeed) -> str | None:
    """Ground-truth English text for generated Hindi/Kannada complaints.

    The corpus templates are translations of the English ones, so the source
    English text is known rather than machine-generated.  (The runtime
    translation model is evaluated separately in ``scripts/evaluate.py``.)
    """
    if seed.language == "en":
        return None
    from app.data.corpus import TEMPLATES

    title, description = TEMPLATES[seed.category]["en"][seed.template_index % 8]
    return f"{title}\n{description}"


def embedding_text_for(seed: ComplaintSeed) -> str:
    """Text used for similarity search: English when a translation exists.

    Multilingual MiniLM places Kannada script and English very far apart, so
    indexing the translated text makes cross-language duplicates comparable.
    """
    return english_translation_for(seed) or seed.text


def seed_users(db, wards) -> tuple[list[dict], list[dict], dict]:
    now = datetime.now(UTC)
    admin = {
        "email": "admin@civiclens.dev",
        "full_name": "City Administrator",
        "role": "admin",
        "ward": None,
        "status": "active",
        "password_hash": hash_password(ADMIN_PASSWORD),
        "created_at": now,
    }
    db["users"].replace_one({"email": admin["email"]}, admin, upsert=True)
    admin_doc = db["users"].find_one({"email": admin["email"]})

    officers: list[dict] = []
    for ward in wards:
        email = f"officer{ward.ward_no}@civiclens.dev"
        doc = {
            "email": email,
            "full_name": f"Ward {ward.ward_no} Officer",
            "role": "ward_officer",
            "ward": ward.ward_no,
            "status": "active",
            "password_hash": hash_password(OFFICER_PASSWORD),
            "created_at": now,
        }
        db["users"].replace_one({"email": email}, doc, upsert=True)
        officers.append(db["users"].find_one({"email": email}))

    citizens: list[dict] = []
    for index in range(1, 6):
        email = f"citizen{index}@civiclens.dev"
        doc = {
            "email": email,
            "full_name": f"Citizen {index}",
            "role": "citizen",
            "ward": 1 + index,
            "status": "active",
            "password_hash": hash_password(CITIZEN_PASSWORD),
            "created_at": now,
        }
        db["users"].replace_one({"email": email}, doc, upsert=True)
        citizens.append(db["users"].find_one({"email": email}))

    return officers, citizens, admin_doc


def build_document(
    seed: ComplaintSeed,
    *,
    settings,
    ward_docs: dict[int, dict],
    citizen_id: str,
    officer_id: str,
    embedding: list[float],
    now: datetime,
) -> dict:
    ward_doc = ward_docs[seed.ward]
    target_hours = settings.sla_targets_hours.get(
        seed.category.value, settings.sla_default_target_hours
    )
    due_at = seed.created_at + timedelta(hours=target_hours)
    open_status = seed.status in (
        ComplaintStatus.SUBMITTED,
        ComplaintStatus.ASSIGNED,
        ComplaintStatus.IN_PROGRESS,
    )
    resolved_at: datetime | None = None
    closed_at: datetime | None = None
    if seed.status in (ComplaintStatus.RESOLVED, ComplaintStatus.CLOSED):
        # Deterministic, category-aware completion time so the dashboard has
        # realistic resolution durations instead of every job finishing in 0 s.
        digest = hashlib.sha256(f"{seed.seed_id}:resolution".encode()).digest()
        factor = 0.35 + int.from_bytes(digest[:2], "big") / 65535 * 2.2
        age_hours = max(1.0, (now - seed.created_at).total_seconds() / 3600)
        hours = min(target_hours * factor, age_hours * 0.82)
        resolved_at = seed.created_at + timedelta(hours=hours)
        if seed.status == ComplaintStatus.CLOSED:
            closed_at = min(resolved_at + timedelta(hours=2), now)
    breached = (
        resolved_at > due_at
        if resolved_at is not None
        else (open_status and due_at <= now)
    )
    sla = SlaState(
        target_hours=target_hours,
        due_at=due_at,
        breached=breached,
        breach_count=1 if breached else 0,
        escalation_level=1 if breached else 0,
        escalation_rung="city" if breached else None,
        escalated_at=due_at if breached else None,
        last_breach_at=due_at if breached else None,
    )
    nearest = nearest_sensitive_km(ward_doc, seed.location)
    priority = compute_priority(
        severity=seed.severity,
        votes=seed.votes,
        cluster_count=0,
        created_at=seed.created_at,
        resolved_at=resolved_at,
        now=now,
        nearest_sensitive_km=nearest,
        weights=settings.priority_weights,
        sensitive_radius_km=settings.priority_sensitive_radius_km,
        max_age_days=settings.priority_max_age_days,
    )
    return {
        "title": seed.title,
        "description": seed.description,
        "category": seed.category.value,
        "severity": seed.severity,
        "location": seed.location.model_dump(),
        "address": seed.address,
        "landmark": seed.landmark,
        "ward": seed.ward,
        "citizen_id": citizen_id,
        "assigned_officer_id": officer_id,
        "status": seed.status.value,
        "votes": seed.votes,
        "voters": [],
        "duplicate_of": None,
        "language": {
            "code": seed.language,
            "name": {"en": "English", "hi": "Hindi", "kn": "Kannada"}[seed.language],
            "confidence": 1.0,
            "method": "script" if seed.language != "en" else "lingua",
        },
        "english_translation": english_translation_for(seed),
        "category_ml": None,
        "enrichment": EnrichmentStatus.DONE.value,
        "priority": priority.model_dump(),
        "sla": sla.model_dump(),
        "resolution": None,
        "resolved_at": resolved_at,
        "closed_at": closed_at,
        "cluster_id": None,
        "attachments": [],
        "embedding": embedding,
        "created_at": seed.created_at,
        "updated_at": closed_at or resolved_at or seed.created_at,
        "benchmark": {
            "corpus": "seed-v1",
            "seed_id": seed.seed_id,
            "duplicate_group": seed.duplicate_group,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="Drop domain collections first.")
    parser.add_argument("--days", type=int, default=120, help="History length in days.")
    parser.add_argument(
        "--skip-embeddings",
        action="store_true",
        help=(
            "Insert complaints without embeddings/Qdrant points "
            "(not useful for similarity tests)."
        ),
    )
    args = parser.parse_args()

    settings = get_settings()
    db = get_sync_database()
    if args.reset:
        for name in DOMAIN_COLLECTIONS:
            db[name].drop()
        print(f"Dropped: {', '.join(DOMAIN_COLLECTIONS)}")
        clear_collection()
        print("Cleared Qdrant collection")

    wards = generate_wards()
    for ward in wards:
        db["wards"].replace_one(
            {"ward_no": ward.ward_no},
            {
                "ward_no": ward.ward_no,
                "name": ward.name,
                "zone": ward.zone,
                "geometry": ward.geometry,
                "sensitive_locations": ward.sensitive_locations,
            },
            upsert=True,
        )
    ward_docs = {doc["ward_no"]: doc for doc in db["wards"].find()}
    print(f"Wards: {len(wards)}")

    officers, citizens, _admin = seed_users(db, wards)
    officer_by_ward = {doc["ward"]: doc for doc in officers}
    print(f"Users: 1 admin, {len(officers)} ward officers, {len(citizens)} citizens")

    seeds = generate_complaints(days=args.days, end_date=datetime.now(UTC).date())
    print(f"Generated {len(seeds)} complaints via app.data.corpus")

    # Embed every unique (English where available) text once, then reuse by text.
    unique_texts = list(dict.fromkeys(embedding_text_for(seed) for seed in seeds))
    if args.skip_embeddings:
        embeddings: dict[str, list[float]] = {}
        print("Skipping embeddings (--skip-embeddings)")
    else:
        print(f"Embedding {len(unique_texts)} unique texts (multilingual MiniLM)...", flush=True)
        vectors = embed_texts(unique_texts)
        embeddings = dict(zip(unique_texts, vectors, strict=True))
        ensure_collection()
        print(f"Embeddings ready ({len(vectors)} vectors of {len(vectors[0])} dims)")

    now = datetime.now(UTC)
    qdrant_batch: list[tuple[str, list[float], dict]] = []
    inserted = 0
    documents: list[dict] = []
    for index, seed in enumerate(seeds):
        citizen = citizens[index % len(citizens)]
        officer = officer_by_ward.get(seed.ward)
        document = build_document(
            seed,
            settings=settings,
            ward_docs=ward_docs,
            citizen_id=str(citizen["_id"]),
            officer_id=str(officer["_id"]) if officer else None,
            embedding=embeddings.get(embedding_text_for(seed), []),
            now=now,
        )
        documents.append(document)

    for batch_start in range(0, len(documents), 500):
        batch = documents[batch_start : batch_start + 500]
        result = db["complaints"].insert_many(batch)
        for document, inserted_id in zip(batch, result.inserted_ids, strict=True):
            inserted += 1
            if document.get("embedding"):
                qdrant_batch.append(
                    (
                        str(inserted_id),
                        document["embedding"],
                        {
                            "category": document["category"],
                            "ward": document["ward"],
                            "status": document["status"],
                            "created_at": document["created_at"].isoformat(),
                            "location": {
                                "lon": document["location"]["coordinates"][0],
                                "lat": document["location"]["coordinates"][1],
                            },
                        },
                    )
                )
            db["audit_events"].insert_one(
                {
                    "action": "created",
                    "complaint_id": str(inserted_id),
                    "actor_id": document["citizen_id"],
                    "actor_role": "citizen",
                    "details": {
                        "seeded": True,
                        "category": document["category"],
                        "ward": document["ward"],
                    },
                    "at": document["created_at"],
                }
            )
        print(f"  inserted {inserted}/{len(documents)}", flush=True)

    if qdrant_batch:
        print(f"Upserting {len(qdrant_batch)} points into Qdrant...", flush=True)
        for start in range(0, len(qdrant_batch), 256):
            for complaint_id, vector, payload in qdrant_batch[start : start + 256]:
                upsert_complaint(complaint_id, vector, payload)
        print("Qdrant points ready")

    print("\nSeed complete.")
    print("  admin     admin@civiclens.dev / Admin#12345")
    print("  officer   officer12@civiclens.dev / Officer#12345")
    print("  citizen   citizen1@civiclens.dev / Citizen#12345")
    print("\nNext: python scripts/train_models.py && python scripts/evaluate.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
