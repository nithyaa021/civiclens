"""RAG-style assistant grounded in complaint data.

Pipeline (no external LLM required):

1. **Retrieve** - embed the question and match it against a curated set of
   example queries (their embeddings are cached in-process) to infer intent.
2. **Parse** - fill slots (ward, category, period, ownership, complaint id)
   from the question text.
3. **Execute** - run structured MongoDB queries inside the caller's
   visibility scope.
4. **Generate** - render a deterministic answer that cites real complaint
   IDs; every sentence is backed by the rows that were fetched.

Visibility: aggregate statistics are treated as public municipal data, but
*citations* (individual complaint records) are restricted: citizens see only
their own reports, ward officers only their ward, admins see everything.
"""

from __future__ import annotations

import re
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from bson import ObjectId

from app.core.config import Settings
from app.core.logging import get_logger
from app.models.complaint import AssistantCitation, AssistantResponse, ComplaintStatus
from app.models.user import Role, UserPublic

logger = get_logger("civiclens.ai.assistant")

OPEN_STATUSES = ("submitted", "assigned", "in_progress")

# (question, intent) - paraphrases that teach the retriever each intent.
EXAMPLES: list[tuple[str, str]] = [
    ("top recurring issues in ward 12 this month", "top_recurring"),
    ("most repeated complaints in ward 5", "top_recurring"),
    ("what are the recurring problems in my area", "top_recurring"),
    ("which issues keep repeating in ward 8", "top_recurring"),
    ("recurring potholes in ward 3", "top_recurring"),
    ("show the most common issues in this ward", "top_recurring"),
    ("status of my pothole report", "status_of"),
    ("what is the status of my complaint", "status_of"),
    ("where is my garbage complaint", "status_of"),
    ("is my streetlight issue resolved yet", "status_of"),
    ("check my water complaint status", "status_of"),
    ("मेरी शिकायत की स्थिति क्या है", "status_of"),
    ("show my complaints", "my_complaints"),
    ("list my open reports", "my_complaints"),
    ("which of my complaints are still open", "my_complaints"),
    ("my recent reports", "my_complaints"),
    ("which complaints are overdue in ward 12", "overdue"),
    ("show breached sla complaints", "overdue"),
    ("what is past its deadline in my ward", "overdue"),
    ("list complaints that missed their deadline", "overdue"),
    ("how many garbage complaints in ward 5 this week", "count_by_category"),
    ("count pothole reports this month", "count_by_category"),
    ("number of water supply complaints in ward 7", "count_by_category"),
    ("how many complaints per category this month", "count_by_category"),
]

# Longer keywords first so "water logging" wins over "water".
CATEGORY_SYNONYMS: dict[str, str] = {
    "pothole": "roads",
    "road damage": "roads",
    "broken road": "roads",
    "footpath": "roads",
    "water logging": "drainage",
    "waterlogging": "drainage",
    "drain": "drainage",
    "sewage": "drainage",
    "flooding": "drainage",
    "water supply": "water_supply",
    "water leak": "water_supply",
    "no water": "water_supply",
    "garbage": "waste_management",
    "waste": "waste_management",
    "trash": "waste_management",
    "streetlight": "streetlight",
    "street light": "streetlight",
    "lamp": "streetlight",
    "signal": "traffic_signal",
    "traffic": "traffic_signal",
    "noise": "noise",
    "tree": "parks_trees",
    "park": "parks_trees",
    "toilet": "sanitation",
    "sanitation": "sanitation",
}

_ordered_synonyms = sorted(CATEGORY_SYNONYMS.items(), key=lambda pair: len(pair[0]), reverse=True)

_example_vectors: list[np.ndarray] | None = None
_example_lock = threading.Lock()


def _ensure_example_vectors() -> list[np.ndarray]:
    global _example_vectors
    if _example_vectors is None:
        with _example_lock:
            if _example_vectors is None:
                from app.ai.embeddings import embed_texts

                vectors = embed_texts([question for question, _ in EXAMPLES])
                _example_vectors = [np.asarray(v, dtype=np.float64) for v in vectors]
    return _example_vectors


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom else 0.0


def _parse_ward(question: str) -> int | None:
    for pattern in (
        r"\bward\s*(?:no\.?\s*|number\s*)?(\d{1,3})\b",
        r"वार्ड\s*(\d{1,3})",
        r"\bw(\d{1,3})\b",
    ):
        match = re.search(pattern, question, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _parse_category(question: str) -> str | None:
    lowered = question.lower()
    for keyword, category in _ordered_synonyms:
        if keyword in lowered:
            return category
    return None


def _parse_complaint_id(question: str) -> str | None:
    match = re.search(r"\b([0-9a-f]{24})\b", question, re.IGNORECASE)
    return match.group(1) if match else None


def _is_own(question: str) -> bool:
    lowered = question.lower()
    return bool(re.search(r"\bmy\b|\bmine\b", lowered)) or any(
        word in question for word in ("मेरी", "मेरा", "मेरे")
    )


def _parse_period(question: str) -> tuple[datetime, datetime, str]:
    lowered = question.lower()
    now = datetime.now(UTC)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if "today" in lowered:
        return midnight, now, "today"
    if "yesterday" in lowered:
        return midnight - timedelta(days=1), midnight, "yesterday"
    if "this week" in lowered or "past week" in lowered or "last 7 days" in lowered:
        return now - timedelta(days=7), now, "the last 7 days"
    if "last week" in lowered:
        return now - timedelta(days=14), now - timedelta(days=7), "last week"
    if "this month" in lowered:
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), now, "this month"
    if "last month" in lowered:
        first_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month_end = first_this - timedelta(seconds=1)
        return last_month_end.replace(day=1), first_this, "last month"
    if "last 30 days" in lowered or "past month" in lowered:
        return now - timedelta(days=30), now, "the last 30 days"
    if "last 3 months" in lowered or "this quarter" in lowered:
        return now - timedelta(days=90), now, "the last 90 days"
    return now - timedelta(days=30), now, "the last 30 days"


def _visible(doc: dict[str, Any], user: UserPublic) -> bool:
    if user.role == Role.ADMIN:
        return True
    if user.role == Role.WARD_OFFICER:
        return doc.get("ward") == user.ward
    return doc.get("citizen_id") == user.id


def _scope_for(user: UserPublic) -> str:
    if user.role == Role.ADMIN:
        return "all"
    if user.role == Role.WARD_OFFICER:
        return "ward"
    return "own"


def _citation(doc: dict[str, Any]) -> AssistantCitation:
    return AssistantCitation(
        complaint_id=str(doc["_id"]),
        title=doc["title"],
        status=ComplaintStatus(doc["status"]),
        category=doc["category"],
    )


async def _retrieve_intent(question: str) -> tuple[str, float]:
    from fastapi.concurrency import run_in_threadpool

    from app.ai.embeddings import embed_one

    query_vector = np.asarray(await run_in_threadpool(embed_one, question), dtype=np.float64)
    vectors = await run_in_threadpool(_ensure_example_vectors)
    scores = [_cosine(query_vector, vector) for vector in vectors]
    best = max(range(len(scores)), key=lambda i: scores[i])
    # Nearest curated example wins.  A majority vote over the top-3 can flip a
    # perfect match (score 1.0) when two weaker paraphrases share another intent.
    intent = EXAMPLES[best][1]
    return intent, round(scores[best], 4)


class Assistant:
    """Grounded question answering for one request."""

    def __init__(self, db: Any, user: UserPublic, settings: Settings) -> None:
        self.db = db
        self.user = user
        self.settings = settings

    async def answer(self, question: str) -> AssistantResponse:
        intent, score = await _retrieve_intent(question)
        if intent == "unknown" or score < self.settings.assistant_min_score:
            return AssistantResponse(
                answer=(
                    "I could not map that question onto complaint data. Try asking about "
                    "recurring issues, a ward, a category, your own reports, or overdue SLAs."
                ),
                intent="unknown",
                scope=_scope_for(self.user),
                citations=[],
                clarification=(
                    "Examples: 'top recurring issues in ward 12 this month', "
                    "'status of my pothole report', 'which complaints are overdue in ward 5'."
                ),
            )

        ward = _parse_ward(question)
        category = _parse_category(question)
        if intent in ("top_recurring", "overdue", "count_by_category") and ward is None:
            # Fall back to the caller's ward context when they have one.
            ward = self.user.ward

        handlers = {
            "top_recurring": self._top_recurring,
            "status_of": self._status_of,
            "my_complaints": self._my_complaints,
            "overdue": self._overdue,
            "count_by_category": self._count_by_category,
        }
        handler = handlers[intent]
        return await handler(question, ward=ward, category=category)

    # --- executions -------------------------------------------------
    async def _citations_from_docs(self, docs: list[dict[str, Any]]) -> list[AssistantCitation]:
        visible = [doc for doc in docs if _visible(doc, self.user)]
        return [_citation(doc) for doc in visible[: self.settings.assistant_max_citations]]

    async def _top_recurring(
        self, question: str, *, ward: int | None, category: str | None
    ) -> AssistantResponse:
        start, _, label = _parse_period(question)
        query: dict[str, Any] = {"last_reported": {"$gte": start}}
        if category:
            query["category"] = category
        if ward is not None:
            query["dominant_ward"] = ward

        clusters = [doc async for doc in self.db["clusters"].find(query).sort("count", -1).limit(5)]
        scope = _scope_for(self.user)

        if clusters:
            lines = [f"Top recurring issues ({label}, ward {ward or self.user.ward or 'all'}):"]
            cited_docs: list[dict[str, Any]] = []
            for index, cluster in enumerate(clusters, start=1):
                lines.append(
                    f"{index}. {cluster['category'].replace('_', ' ')} — "
                    f"{cluster['count']} reports, "
                    f"{cluster['open_count']} still open; first reported "
                    f"{cluster['first_reported'].date()}, last {cluster['last_reported'].date()}."
                )
                member_ids = [
                    ObjectId(cid) for cid in cluster["complaint_ids"] if ObjectId.is_valid(cid)
                ]
                cited_docs.extend(
                    [
                        doc
                        async for doc in self.db["complaints"].find(
                            {"_id": {"$in": member_ids}},
                            {"title": 1, "status": 1, "category": 1, "ward": 1, "citizen_id": 1},
                        )
                    ]
                )
            citations = await self._citations_from_docs(cited_docs)
            if not citations and self.user.role != Role.ADMIN:
                lines.append(
                    "No complaint IDs are cited: those records are outside your visibility scope."
                )
            return AssistantResponse(
                answer="\n".join(lines), intent="top_recurring", scope=scope, citations=citations
            )

        # Fallback: plain category counts when no clusters match.
        match: dict[str, Any] = {"created_at": {"$gte": start}}
        if ward is not None:
            match["ward"] = ward
        if category:
            match["category"] = category
        counts = [
            row
            async for row in self.db["complaints"].aggregate(
                [
                    {"$match": match},
                    {"$group": {"_id": "$category", "n": {"$sum": 1}}},
                    {"$sort": {"n": -1}},
                ]
            )
        ]
        if not counts:
            return AssistantResponse(
                answer=f"No complaints found for {label}.",
                intent="top_recurring",
                scope=scope,
                citations=[],
            )
        summary = ", ".join(f"{row['_id'].replace('_', ' ')} ({row['n']})" for row in counts[:6])
        top_docs = [
            doc
            async for doc in self.db["complaints"]
            .find(match)
            .sort("created_at", -1)
            .limit(self.settings.assistant_max_citations)
        ]
        return AssistantResponse(
            answer=(f"No tight recurring clusters for {label}; volume by category: {summary}."),
            intent="top_recurring",
            scope=scope,
            citations=await self._citations_from_docs(top_docs),
        )

    async def _status_of(
        self, question: str, *, ward: int | None, category: str | None
    ) -> AssistantResponse:
        scope = _scope_for(self.user)
        complaint_id = _parse_complaint_id(question)

        if complaint_id and ObjectId.is_valid(complaint_id):
            doc = await self.db["complaints"].find_one({"_id": ObjectId(complaint_id)})
            if doc is None or not _visible(doc, self.user):
                return AssistantResponse(
                    answer="That complaint id is not in your visible records.",
                    intent="status_of",
                    scope=scope,
                    citations=[],
                )
            return self._status_response(doc, scope)

        query: dict[str, Any] = {}
        if self.user.role == Role.CITIZEN or _is_own(question):
            query["citizen_id"] = self.user.id
        elif self.user.role == Role.WARD_OFFICER:
            query["ward"] = self.user.ward
        if category:
            query["category"] = category
        if ward is not None and self.user.role != Role.CITIZEN:
            query["ward"] = ward

        docs = [
            doc async for doc in self.db["complaints"].find(query).sort("created_at", -1).limit(5)
        ]
        if not docs:
            return AssistantResponse(
                answer="I could not find a matching complaint in your visible records.",
                intent="status_of",
                scope=scope,
                citations=[],
                clarification="Mention the category (e.g. 'pothole') or paste the complaint id.",
            )
        return self._status_response(docs[0], scope)

    def _status_response(self, doc: dict[str, Any], scope: str) -> AssistantResponse:
        sla = doc.get("sla") or {}
        priority = doc.get("priority") or {}
        parts = [
            f"Report '{doc['title']}' "
            f"({doc['category'].replace('_', ' ')}, Ward {doc.get('ward')}) "
            f"is currently {doc['status'].replace('_', ' ')}."
        ]
        if sla.get("due_at"):
            parts.append(f"SLA target {sla.get('target_hours')}h, due {sla['due_at'].date()}.")
            if sla.get("breached"):
                parts.append(f"It is escalated to level {sla.get('escalation_level')}.")
        if priority.get("score") is not None:
            parts.append(f"Priority score {priority['score']}/100.")
        if doc.get("resolution"):
            verification = doc["resolution"].get("verification") or {}
            if verification:
                parts.append(
                    f"Image verification confidence {verification.get('confidence')} "
                    f"({'passed' if verification.get('passed') else 'failed'})."
                )
        return AssistantResponse(
            answer=" ".join(parts),
            intent="status_of",
            scope=scope,
            citations=[_citation(doc)],
        )

    async def _my_complaints(
        self, question: str, *, ward: int | None, category: str | None
    ) -> AssistantResponse:
        query: dict[str, Any] = {}
        if self.user.role == Role.WARD_OFFICER:
            query["assigned_officer_id"] = self.user.id
        else:
            query["citizen_id"] = self.user.id
        if category:
            query["category"] = category

        docs = [
            doc
            async for doc in self.db["complaints"]
            .find(query)
            .sort("created_at", -1)
            .limit(self.settings.assistant_max_citations)
        ]
        if not docs:
            return AssistantResponse(
                answer="You have no reports matching that request.",
                intent="my_complaints",
                scope=_scope_for(self.user),
                citations=[],
            )
        open_docs = [doc for doc in docs if doc["status"] in OPEN_STATUSES]
        lines = [f"You have {len(docs)} matching report(s), {len(open_docs)} still open:"]
        for doc in docs[:5]:
            lines.append(
                f"- {doc['title']} — {doc['status'].replace('_', ' ')} (Ward {doc.get('ward')})"
            )
        return AssistantResponse(
            answer="\n".join(lines),
            intent="my_complaints",
            scope=_scope_for(self.user),
            citations=[_citation(doc) for doc in docs[: self.settings.assistant_max_citations]],
        )

    async def _overdue(
        self, question: str, *, ward: int | None, category: str | None
    ) -> AssistantResponse:
        now = datetime.now(UTC)
        query: dict[str, Any] = {"status": {"$in": list(OPEN_STATUSES)}, "sla.due_at": {"$lt": now}}
        if ward is not None:
            query["ward"] = ward
        if category:
            query["category"] = category
        if self.user.role == Role.CITIZEN:
            query["citizen_id"] = self.user.id
        elif self.user.role == Role.WARD_OFFICER:
            query["ward"] = self.user.ward

        total = await self.db["complaints"].count_documents(query)
        docs = [
            doc async for doc in self.db["complaints"].find(query).sort("sla.due_at", 1).limit(5)
        ]
        if total == 0:
            return AssistantResponse(
                answer="No overdue complaints in your scope.",
                intent="overdue",
                scope=_scope_for(self.user),
                citations=[],
            )
        lines = [f"{total} complaint(s) are past their SLA deadline in your scope:"]
        for doc in docs:
            overdue_hours = (now - doc["sla"]["due_at"]).total_seconds() / 3600.0
            lines.append(
                f"- {doc['title']} (Ward {doc.get('ward')}) — {overdue_hours:.0f}h overdue, "
                f"escalation level {doc.get('sla', {}).get('escalation_level', 0)}"
            )
        return AssistantResponse(
            answer="\n".join(lines),
            intent="overdue",
            scope=_scope_for(self.user),
            citations=[_citation(doc) for doc in docs],
        )

    async def _count_by_category(
        self, question: str, *, ward: int | None, category: str | None
    ) -> AssistantResponse:
        start, end, label = _parse_period(question)
        match: dict[str, Any] = {"created_at": {"$gte": start, "$lte": end}}
        if ward is not None:
            match["ward"] = ward
        if category:
            match["category"] = category

        rows = [
            row
            async for row in self.db["complaints"].aggregate(
                [
                    {"$match": match},
                    {"$group": {"_id": "$category", "n": {"$sum": 1}}},
                    {"$sort": {"n": -1}},
                ]
            )
        ]
        if not rows:
            return AssistantResponse(
                answer=f"No complaints recorded for {label}.",
                intent="count_by_category",
                scope=_scope_for(self.user),
                citations=[],
            )
        total = sum(row["n"] for row in rows)
        summary = ", ".join(f"{row['_id'].replace('_', ' ')}: {row['n']}" for row in rows)
        top_category = rows[0]["_id"]
        top_docs = [
            doc
            async for doc in self.db["complaints"]
            .find({**match, "category": top_category})
            .sort("created_at", -1)
            .limit(self.settings.assistant_max_citations)
        ]
        where = f" in ward {ward}" if ward is not None else ""
        return AssistantResponse(
            answer=f"{total} complaint(s) for {label}{where} — {summary}.",
            intent="count_by_category",
            scope=_scope_for(self.user),
            citations=await self._citations_from_docs(top_docs),
        )
