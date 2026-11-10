"""Complaint lifecycle services: creation, workflow, voting, resolution."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from app.ai.priority import compute_priority
from app.core.config import Settings
from app.core.errors import ApiError, ConflictError, ForbiddenError, NotFoundError
from app.models.common import Page
from app.models.complaint import (
    ALLOWED_TRANSITIONS,
    AttachmentRef,
    ComplaintCreate,
    ComplaintPublic,
    ComplaintStatus,
    ComplaintSummary,
    EnrichmentStatus,
    InternalNote,
    InternalNoteCreate,
    InternalNoteList,
    LanguageInfo,
    MlSuggestion,
    PriorityScore,
    ResolutionRecord,
    SimilarIssue,
    SimilarIssueQuery,
    SimilarIssueResponse,
    SlaState,
)
from app.models.user import Role, UserPublic
from app.services import audit
from app.services.wards import nearest_sensitive_km, resolve_ward_or_raise

CLOSABLE_BY_OFFICER = {Role.ADMIN}  # RESOLVED -> CLOSED via PATCH is admin-only


def _oid(complaint_id: str) -> ObjectId:
    if not ObjectId.is_valid(complaint_id):
        raise NotFoundError("Complaint", complaint_id)
    return ObjectId(complaint_id)


def _visible_citizen_id(doc: dict[str, Any], viewer: UserPublic) -> str | None:
    """Reporter identity is visible to the owner, the ward officer and admins."""
    if (
        viewer.role == Role.ADMIN
        or viewer.role == Role.WARD_OFFICER
        or viewer.id == doc.get("citizen_id")
    ):
        return doc.get("citizen_id")
    return None


def serialize(doc: dict[str, Any], viewer: UserPublic) -> ComplaintPublic:
    """Convert a Mongo complaint document into :class:`ComplaintPublic`."""
    language = doc.get("language")
    category_ml = doc.get("category_ml")
    priority = doc.get("priority")
    sla = doc.get("sla")
    resolution = doc.get("resolution")
    return ComplaintPublic(
        id=str(doc["_id"]),
        title=doc["title"],
        description=doc["description"],
        category=doc["category"],
        severity=doc["severity"],
        location=doc["location"],
        address=doc["address"],
        landmark=doc.get("landmark"),
        status=ComplaintStatus(doc["status"]),
        ward=doc.get("ward"),
        citizen_id=_visible_citizen_id(doc, viewer),
        assigned_officer_id=doc.get("assigned_officer_id"),
        votes=int(doc.get("votes", 0)),
        duplicate_of=doc.get("duplicate_of"),
        language=LanguageInfo(**language) if language else None,
        english_translation=doc.get("english_translation"),
        category_ml=MlSuggestion(**category_ml) if category_ml else None,
        enrichment=EnrichmentStatus(doc.get("enrichment", EnrichmentStatus.PENDING.value)),
        priority=PriorityScore(**priority) if priority else None,
        sla=SlaState(**sla) if sla else None,
        resolution=ResolutionRecord(**resolution) if resolution else None,
        cluster_id=doc.get("cluster_id"),
        attachments=[AttachmentRef(**item) for item in doc.get("attachments", [])],
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


def summarize(doc: dict[str, Any]) -> ComplaintSummary:
    """Compact card used in similarity / cluster / assistant responses."""
    return ComplaintSummary(
        id=str(doc["_id"]),
        title=doc["title"],
        category=doc["category"],
        status=doc["status"],
        severity=doc["severity"],
        ward=doc.get("ward"),
        votes=int(doc.get("votes", 0)),
        location=doc["location"],
        address=doc["address"],
        created_at=doc["created_at"],
    )


# --- Creation -----------------------------------------------------------------
async def create_complaint(
    db: AsyncIOMotorDatabase,
    payload: ComplaintCreate,
    citizen: UserPublic,
    settings: Settings,
) -> ComplaintPublic:
    """File a complaint: resolve ward, auto-assign officer, start the SLA clock."""
    ward_doc = await resolve_ward_or_raise(db, payload.location)
    now = datetime.now(UTC)

    if payload.duplicate_of is not None:
        if not ObjectId.is_valid(payload.duplicate_of):
            raise ApiError(400, "unknown_duplicate", "duplicate_of is not a valid complaint id.")
        linked = await db["complaints"].count_documents(
            {"_id": ObjectId(payload.duplicate_of)}, limit=1
        )
        if linked == 0:
            raise ApiError(400, "unknown_duplicate", "duplicate_of does not exist.")

    officer = await db["users"].find_one(
        {"role": Role.WARD_OFFICER.value, "ward": ward_doc["ward_no"], "status": "active"},
        sort=[("created_at", 1)],
    )
    target_hours = settings.sla_targets_hours.get(
        payload.category.value, settings.sla_default_target_hours
    )
    nearest_km = nearest_sensitive_km(ward_doc, payload.location)
    initial_priority = compute_priority(
        severity=payload.severity,
        votes=0,
        cluster_count=0,
        created_at=now,
        resolved_at=None,
        now=now,
        nearest_sensitive_km=nearest_km,
        weights=settings.priority_weights,
        sensitive_radius_km=settings.priority_sensitive_radius_km,
        max_age_days=settings.priority_max_age_days,
    )

    doc: dict[str, Any] = {
        "title": payload.title.strip(),
        "description": payload.description.strip(),
        "category": payload.category.value,
        "severity": payload.severity,
        "location": payload.location.model_dump(),
        "address": payload.address.strip(),
        "landmark": payload.landmark,
        "ward": ward_doc["ward_no"],
        "citizen_id": citizen.id,
        "assigned_officer_id": str(officer["_id"]) if officer else None,
        "status": ComplaintStatus.ASSIGNED.value if officer else ComplaintStatus.SUBMITTED.value,
        "votes": 0,
        "voters": [],
        "duplicate_of": payload.duplicate_of,
        "language": None,
        "english_translation": None,
        "category_ml": None,
        "enrichment": EnrichmentStatus.PENDING.value,
        "priority": initial_priority.model_dump(),
        "sla": SlaState(
            target_hours=target_hours,
            due_at=now + timedelta(hours=target_hours),
        ).model_dump(),
        "resolution": None,
        "cluster_id": None,
        "attachments": [],
        "created_at": now,
        "updated_at": now,
    }
    result = await db["complaints"].insert_one(doc)
    doc["_id"] = result.inserted_id
    complaint_id = str(result.inserted_id)

    await audit.record_event(
        db,
        action="created",
        complaint_id=complaint_id,
        actor_id=citizen.id,
        actor_role=citizen.role.value,
        details={"category": doc["category"], "ward": doc["ward"], "severity": doc["severity"]},
    )
    if officer is not None:
        await audit.record_event(
            db,
            action="auto_assigned",
            complaint_id=complaint_id,
            actor_id=None,
            actor_role="system",
            details={"officer_id": str(officer["_id"]), "ward": doc["ward"]},
        )
        from app.workers.tasks.notifications import send_notification

        send_notification.delay(
            user_id=str(officer["_id"]),
            subject="New complaint assigned",
            body=f"'{doc['title']}' was filed in Ward {doc['ward']} and assigned to you.",
            channel="in_app",
            requested_by=citizen.id,
        )
    return serialize(doc, citizen)


# --- Reads --------------------------------------------------------------------
async def get_complaint(
    db: AsyncIOMotorDatabase, complaint_id: str, viewer: UserPublic
) -> ComplaintPublic:
    doc = await db["complaints"].find_one({"_id": _oid(complaint_id)})
    if doc is None:
        raise NotFoundError("Complaint", complaint_id)
    return serialize(doc, viewer)


async def list_complaints(
    db: AsyncIOMotorDatabase,
    viewer: UserPublic,
    *,
    page: int,
    page_size: int,
    status: ComplaintStatus | None = None,
    category: str | None = None,
    ward: int | None = None,
    mine: bool = False,
    q: str | None = None,
    sort: str = "newest",
) -> Page[ComplaintPublic]:
    """Paginated, filterable complaint listing (municipal records are public
    to authenticated users; ``mine`` narrows to the caller's own reports)."""
    query: dict[str, Any] = {}
    if mine:
        query["citizen_id"] = viewer.id
    if status is not None:
        query["status"] = status.value
    if category is not None:
        query["category"] = category
    if ward is not None:
        query["ward"] = ward
    if q:
        query["$text"] = {"$search": q}

    sort_spec: list[tuple[str, int]] = {
        "newest": [("created_at", -1)],
        "oldest": [("created_at", 1)],
        "priority": [("priority.score", -1)],
        "due": [("sla.due_at", 1)],
    }.get(sort, [("created_at", -1)])

    total = await db["complaints"].count_documents(query)
    cursor = (
        db["complaints"].find(query).sort(sort_spec).skip((page - 1) * page_size).limit(page_size)
    )
    items = [serialize(doc, viewer) async for doc in cursor]
    return Page[ComplaintPublic](items=items, total=total, page=page, page_size=page_size)


# --- Workflow -----------------------------------------------------------------
async def update_status(
    db: AsyncIOMotorDatabase,
    complaint_id: str,
    new_status: ComplaintStatus,
    note: str | None,
    actor: UserPublic,
) -> ComplaintPublic:
    """Guarded status transition with RBAC, audit trail and citizen notify."""
    oid = _oid(complaint_id)
    current_doc = await db["complaints"].find_one({"_id": oid})
    if current_doc is None:
        raise NotFoundError("Complaint", complaint_id)
    current = ComplaintStatus(current_doc["status"])

    if actor.role == Role.CITIZEN:
        raise ForbiddenError(
            "Citizens change resolution state through confirm/dispute, not status updates."
        )
    if new_status == current:
        raise ConflictError(
            f"Complaint is already in status {current.value!r}.",
            details={"status": current.value},
        )
    if new_status not in ALLOWED_TRANSITIONS[current]:
        raise ApiError(
            400,
            "invalid_transition",
            f"Cannot move a complaint from {current.value!r} to {new_status.value!r}.",
            details={"from": current.value, "to": new_status.value},
        )
    if actor.role == Role.WARD_OFFICER:
        if current_doc.get("ward") != actor.ward:
            raise ForbiddenError("You can only manage complaints in your assigned ward.")
        if current == ComplaintStatus.CLOSED or (
            current == ComplaintStatus.RESOLVED and new_status == ComplaintStatus.CLOSED
        ):
            raise ForbiddenError("Closing a resolved complaint is confirmed by the citizen.")
    if current == ComplaintStatus.CLOSED and actor.role != Role.ADMIN:
        raise ForbiddenError("Only admins may reopen a closed complaint.")
    if new_status == ComplaintStatus.RESOLVED:
        resolution = current_doc.get("resolution") or {}
        verification = resolution.get("verification")
        if actor.role != Role.ADMIN and not (verification and verification.get("passed")):
            raise ConflictError(
                "Resolution requires a verified after-photo upload "
                "(POST /api/v1/complaints/{id}/resolution).",
                details={"reason": "verification_required"},
            )

    now = datetime.now(UTC)
    update: dict[str, Any] = {"status": new_status.value, "updated_at": now}
    if new_status == ComplaintStatus.RESOLVED:
        update["resolved_at"] = now
    elif new_status == ComplaintStatus.IN_PROGRESS and current == ComplaintStatus.RESOLVED:
        update["resolved_at"] = None
    elif new_status == ComplaintStatus.CLOSED:
        update["closed_at"] = now

    # Guard on the observed status so concurrent transitions cannot skip checks.
    updated = await db["complaints"].find_one_and_update(
        {"_id": oid, "status": current.value},
        {"$set": update},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise ConflictError("The complaint changed while updating; refresh and retry.")

    await audit.record_event(
        db,
        action="status_changed",
        complaint_id=complaint_id,
        actor_id=actor.id,
        actor_role=actor.role.value,
        details={"from": current.value, "to": new_status.value, "note": note},
    )
    if updated.get("citizen_id") and updated["citizen_id"] != actor.id:
        from app.workers.tasks.notifications import send_notification

        send_notification.delay(
            user_id=updated["citizen_id"],
            subject=f"Complaint update: {new_status.value.replace('_', ' ')}",
            body=f"Your report '{updated['title']}' is now {new_status.value.replace('_', ' ')}."
            + (f" Note: {note}" if note else ""),
            channel="in_app",
            requested_by=actor.id,
        )
    return serialize(updated, actor)


# --- Staff notes and assignment ------------------------------------------------
async def _staff_visible_complaint(
    db: AsyncIOMotorDatabase, complaint_id: str, actor: UserPublic
) -> dict[str, Any]:
    """Load a complaint for a staff action, enforcing ward scope."""
    if actor.role == Role.CITIZEN:
        raise ForbiddenError("This action is restricted to ward officers and administrators.")
    oid = _oid(complaint_id)
    doc = await db["complaints"].find_one({"_id": oid})
    if doc is None:
        raise NotFoundError("Complaint", complaint_id)
    if actor.role == Role.WARD_OFFICER and doc.get("ward") != actor.ward:
        raise ForbiddenError("You can only manage complaints in your assigned ward.")
    return doc


async def assign_officer(
    db: AsyncIOMotorDatabase,
    complaint_id: str,
    officer_id: str,
    actor: UserPublic,
) -> ComplaintPublic:
    """Assign (or reassign) a complaint to an active ward officer."""
    current = await _staff_visible_complaint(db, complaint_id, actor)
    if not ObjectId.is_valid(officer_id):
        raise NotFoundError("Officer", officer_id)
    officer = await db["users"].find_one({"_id": ObjectId(officer_id)})
    if officer is None or officer.get("role") != Role.WARD_OFFICER.value:
        raise ApiError(400, "invalid_officer", "Choose an active ward officer.")
    if officer.get("status") != "active":
        raise ApiError(400, "inactive_officer", "That officer account is inactive.")
    if actor.role == Role.WARD_OFFICER and officer.get("ward") != actor.ward:
        raise ForbiddenError("You can only assign complaints inside your ward.")
    if current["status"] == ComplaintStatus.CLOSED.value:
        raise ConflictError("Closed complaints cannot be reassigned.")

    now = datetime.now(UTC)
    update: dict[str, Any] = {"assigned_officer_id": officer_id, "updated_at": now}
    if current["status"] == ComplaintStatus.SUBMITTED.value:
        update["status"] = ComplaintStatus.ASSIGNED.value
    updated = await db["complaints"].find_one_and_update(
        {"_id": current["_id"], "status": current["status"]},
        {"$set": update},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise ConflictError("The complaint changed while assigning; refresh and retry.")

    await audit.record_event(
        db,
        action="assigned",
        complaint_id=complaint_id,
        actor_id=actor.id,
        actor_role=actor.role.value,
        details={
            "from": current.get("assigned_officer_id"),
            "to": officer_id,
            "officer_name": officer.get("full_name"),
            "ward": officer.get("ward"),
        },
    )
    if officer_id != actor.id:
        from app.workers.tasks.notifications import send_notification

        send_notification.delay(
            user_id=officer_id,
            subject="Complaint assigned to you",
            body=f"'{updated['title']}' in ward {updated.get('ward')} is now in your queue.",
            channel="in_app",
            requested_by=actor.id,
        )
    return serialize(updated, actor)


async def list_internal_notes(
    db: AsyncIOMotorDatabase, complaint_id: str, actor: UserPublic
) -> InternalNoteList:
    """Staff-only notes for one complaint, oldest first."""
    await _staff_visible_complaint(db, complaint_id, actor)
    items = [
        InternalNote(
            id=str(doc["_id"]),
            complaint_id=doc["complaint_id"],
            author_id=doc["author_id"],
            author_name=doc["author_name"],
            author_role=doc["author_role"],
            note=doc["note"],
            created_at=doc["created_at"],
        )
        async for doc in db["complaint_notes"].find({"complaint_id": complaint_id}).sort(
            "created_at", 1
        )
    ]
    return InternalNoteList(items=items, total=len(items))


async def add_internal_note(
    db: AsyncIOMotorDatabase,
    complaint_id: str,
    payload: InternalNoteCreate,
    actor: UserPublic,
) -> InternalNote:
    """Append a staff note and mirror it into the audit trail."""
    await _staff_visible_complaint(db, complaint_id, actor)
    now = datetime.now(UTC)
    doc = {
        "complaint_id": complaint_id,
        "author_id": actor.id,
        "author_name": actor.full_name,
        "author_role": actor.role.value,
        "note": payload.note.strip(),
        "created_at": now,
    }
    result = await db["complaint_notes"].insert_one(doc)
    await audit.record_event(
        db,
        action="internal_note",
        complaint_id=complaint_id,
        actor_id=actor.id,
        actor_role=actor.role.value,
        details={"note": payload.note.strip()},
    )
    return InternalNote(id=str(result.inserted_id), **doc)


# --- Voting (upvote instead of duplicating) -----------------------------------
async def vote(
    db: AsyncIOMotorDatabase, complaint_id: str, citizen: UserPublic, *, add: bool
) -> ComplaintPublic:
    """Idempotent upvote (or retraction) supporting the de-duplication flow."""
    oid = _oid(complaint_id)
    current = await db["complaints"].find_one({"_id": oid})
    if current is None:
        raise NotFoundError("Complaint", complaint_id)

    already = citizen.id in (current.get("voters") or [])
    if add and already:
        return serialize(current, citizen)
    if not add and not already:
        return serialize(current, citizen)

    if add:
        query: dict[str, Any] = {"_id": oid, "voters": {"$ne": citizen.id}}
        update: dict[str, Any] = {"$addToSet": {"voters": citizen.id}, "$inc": {"votes": 1}}
    else:
        query = {"_id": oid, "voters": citizen.id}
        update = {"$pull": {"voters": citizen.id}, "$inc": {"votes": -1}}

    updated = await db["complaints"].find_one_and_update(
        query, update, return_document=ReturnDocument.AFTER
    )
    if updated is None:  # concurrent vote resolved the race; re-read state
        updated = await db["complaints"].find_one({"_id": oid})
        assert updated is not None
    return serialize(updated, citizen)


# --- Attachments --------------------------------------------------------------
async def add_attachment(
    db: AsyncIOMotorDatabase,
    complaint_id: str,
    *,
    kind: str,
    filename: str,
    content_type: str,
    data: bytes,
    actor: UserPublic,
) -> AttachmentRef:
    """Store an uploaded photo and link it to the complaint."""
    from app.models.complaint import MAX_ATTACHMENTS_PER_COMPLAINT

    oid = _oid(complaint_id)
    current = await db["complaints"].find_one({"_id": oid})
    if current is None:
        raise NotFoundError("Complaint", complaint_id)

    if actor.role == Role.CITIZEN and actor.id != current.get("citizen_id"):
        raise ForbiddenError("You can only attach photos to your own complaints.")
    if actor.role == Role.WARD_OFFICER and current.get("ward") != actor.ward:
        raise ForbiddenError("You can only attach photos to complaints in your ward.")
    attachments = current.get("attachments") or []
    if len(attachments) >= MAX_ATTACHMENTS_PER_COMPLAINT:
        raise ConflictError(
            f"A complaint may have at most {MAX_ATTACHMENTS_PER_COMPLAINT} attachments."
        )

    now = datetime.now(UTC)
    media = await db["media"].insert_one(
        {
            "filename": filename,
            "content_type": content_type,
            "size_bytes": len(data),
            "data": data,
            "owner_id": actor.id,
            "complaint_id": complaint_id,
            "purpose": kind,
            "created_at": now,
        }
    )
    ref = {
        "id": str(media.inserted_id),
        "kind": kind,
        "content_type": content_type,
        "created_at": now,
    }
    updated = await db["complaints"].find_one_and_update(
        {"_id": oid},
        {"$push": {"attachments": ref}, "$set": {"updated_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    assert updated is not None
    return AttachmentRef(**ref)


# --- Resolution verification --------------------------------------------------
async def request_resolution(
    db: AsyncIOMotorDatabase,
    complaint_id: str,
    *,
    after_media_id: str,
    note: str | None,
    actor: UserPublic,
) -> ComplaintPublic:
    """Officer submits an after-photo; verification runs asynchronously."""
    oid = _oid(complaint_id)
    current = await db["complaints"].find_one({"_id": oid})
    if current is None:
        raise NotFoundError("Complaint", complaint_id)
    if actor.role == Role.CITIZEN:
        raise ForbiddenError("Only ward officers and admins may submit a resolution.")
    if actor.role == Role.WARD_OFFICER and current.get("ward") != actor.ward:
        raise ForbiddenError("You can only resolve complaints in your assigned ward.")

    status = ComplaintStatus(current["status"])
    if status not in (ComplaintStatus.ASSIGNED, ComplaintStatus.IN_PROGRESS):
        raise ConflictError(
            f"A resolution can only be submitted while the complaint is assigned or "
            f"in progress (currently {status.value!r}).",
            details={"status": status.value},
        )
    if not any(a.get("kind") == "before" for a in current.get("attachments") or []):
        raise ConflictError(
            "Attach a 'before' photo first - resolution verification compares it "
            "with your after-photo.",
            details={"reason": "before_photo_required"},
        )
    if not ObjectId.is_valid(after_media_id):
        raise ApiError(400, "unknown_media", "after_media_id is not a valid media id.")

    now = datetime.now(UTC)
    record = ResolutionRecord(
        after_media_id=after_media_id,
        officer_id=actor.id,
        note=note,
        created_at=now,
    )
    # Guard on status so a concurrent transition cannot clobber the record.
    updated = await db["complaints"].find_one_and_update(
        {
            "_id": oid,
            "status": {
                "$in": [s.value for s in (ComplaintStatus.ASSIGNED, ComplaintStatus.IN_PROGRESS)]
            },
        },
        {"$set": {"resolution": record.model_dump(), "updated_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise ConflictError("The complaint status changed; refresh and retry.")

    await audit.record_event(
        db,
        action="resolution_submitted",
        complaint_id=complaint_id,
        actor_id=actor.id,
        actor_role=actor.role.value,
        details={"after_media_id": after_media_id, "note": note},
    )
    return serialize(updated, actor)


async def record_citizen_decision(
    db: AsyncIOMotorDatabase,
    complaint_id: str,
    *,
    decision: str,
    note: str | None,
    citizen: UserPublic,
) -> ComplaintPublic:
    """Citizen confirms (close) or disputes (reopen) a verified resolution."""
    if decision not in ("confirmed", "disputed"):
        raise ApiError(400, "invalid_decision", "decision must be 'confirmed' or 'disputed'.")
    oid = _oid(complaint_id)
    current = await db["complaints"].find_one({"_id": oid})
    if current is None:
        raise NotFoundError("Complaint", complaint_id)
    if citizen.role == Role.CITIZEN and citizen.id != current.get("citizen_id"):
        raise ForbiddenError("Only the reporter may confirm or dispute a resolution.")
    if ComplaintStatus(current["status"]) != ComplaintStatus.RESOLVED:
        raise ConflictError(
            "This complaint is not in the resolved state.",
            details={"status": current["status"]},
        )
    resolution = current.get("resolution") or {}
    if not (resolution.get("verification") or {}).get("passed"):
        raise ConflictError("This resolution has not passed image verification.")

    now = datetime.now(UTC)
    new_status = ComplaintStatus.CLOSED if decision == "confirmed" else ComplaintStatus.IN_PROGRESS
    update: dict[str, Any] = {
        "status": new_status.value,
        "updated_at": now,
        "resolution.citizen_decision": decision,
        "resolution.decision_note": note,
        "resolution.decided_at": now,
    }
    if decision == "confirmed":
        update["closed_at"] = now
    else:
        update["resolved_at"] = None

    updated = await db["complaints"].find_one_and_update(
        {"_id": oid, "status": ComplaintStatus.RESOLVED.value},
        {"$set": update},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise ConflictError("The complaint changed while recording your decision.")

    await audit.record_event(
        db,
        action=f"resolution_{decision}",
        complaint_id=complaint_id,
        actor_id=citizen.id,
        actor_role=citizen.role.value,
        details={"note": note},
    )
    officer_id = resolution.get("officer_id")
    if officer_id:
        from app.workers.tasks.notifications import send_notification

        send_notification.delay(
            user_id=officer_id,
            subject=f"Resolution {decision}",
            body=f"The reporter {decision} the fix for '{updated['title']}'."
            + (f" Note: {note}" if note else ""),
            channel="in_app",
            requested_by=citizen.id,
        )
    return serialize(updated, citizen)


# --- Pre-submit similarity ----------------------------------------------------
async def find_similar_issues(
    db: AsyncIOMotorDatabase,
    payload: SimilarIssueQuery,
    settings: Settings,
) -> SimilarIssueResponse:
    """Embed the draft text and return indexed near-duplicates nearby."""
    from fastapi.concurrency import run_in_threadpool

    from app.ai.clustering import haversine_km
    from app.ai.embeddings import embed_one
    from app.ai.language import detect_language
    from app.ai.translation import translate_to_english
    from app.ai.vector_store import search_similar

    language = await run_in_threadpool(detect_language, payload.text)
    embedding_text = payload.text
    if language.code != "en":
        [translated] = await run_in_threadpool(
            translate_to_english, [payload.text], [language.code]
        )
        if translated.strip():
            embedding_text = translated
    vector = await run_in_threadpool(embed_one, embedding_text)

    radius = payload.radius_km or settings.similar_geo_radius_km
    limit = payload.limit or settings.similar_top_k
    center = payload.location
    hits = await run_in_threadpool(
        search_similar,
        vector,
        limit=limit * 3,  # over-fetch: Mongo hydration + distance filter below
        min_score=settings.similar_min_score,
        category=payload.category.value if payload.category else None,
        center_lng=center.lng if center else None,
        center_lat=center.lat if center else None,
        radius_km=radius if center else None,
    )
    if not hits:
        return SimilarIssueResponse(
            items=[], query_language=language, min_score=settings.similar_min_score
        )

    ids = [ObjectId(hit_id) for hit_id, _, _ in hits if ObjectId.is_valid(hit_id)]
    docs = {str(doc["_id"]): doc async for doc in db["complaints"].find({"_id": {"$in": ids}})}

    items: list[SimilarIssue] = []
    for hit_id, score, _payload in hits:
        doc = docs.get(hit_id)
        if doc is None:
            continue
        distance = None
        if center is not None:
            lng, lat = doc["location"]["coordinates"]
            distance = round(haversine_km(center.lng, center.lat, lng, lat), 3)
        items.append(
            SimilarIssue(complaint=summarize(doc), score=round(score, 4), distance_km=distance)
        )
    items.sort(key=lambda item: item.score, reverse=True)
    return SimilarIssueResponse(
        items=items[:limit],
        query_language=language,
        min_score=settings.similar_min_score,
    )
