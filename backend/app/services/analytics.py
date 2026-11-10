"""Aggregations for the authority dashboard and public transparency portal."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.errors import ForbiddenError
from app.models.analytics import (
    CategoryStat,
    ComplaintMapResponse,
    KpiSummary,
    MapComplaint,
    OverviewResponse,
    PublicCategoryStat,
    PublicResolution,
    PublicStats,
    PublicWardStat,
    TrendPoint,
)
from app.models.complaint import ComplaintStatus
from app.models.user import Role, UserPublic

OPEN_STATUSES = ("submitted", "assigned", "in_progress")
RESOLVED_STATUSES = ("resolved", "closed")
DEFAULT_PERIOD_DAYS = 30
PUBLIC_PERIOD_DAYS = 90


def _scope(actor: UserPublic) -> tuple[dict[str, Any], str, int | None]:
    """Role scope for every staff aggregation."""
    if actor.role == Role.ADMIN:
        return {}, "all", None
    if actor.role == Role.WARD_OFFICER:
        if actor.ward is None:
            raise ForbiddenError("Ward officer accounts need an assigned ward.")
        return {"ward": actor.ward}, "ward", actor.ward
    raise ForbiddenError("The authority dashboard is restricted to staff accounts.")


def _resolved_at(doc: dict[str, Any]) -> datetime | None:
    """Best available completion timestamp, including older seeded records."""
    if doc.get("resolved_at"):
        return doc["resolved_at"]
    if doc.get("closed_at"):
        return doc["closed_at"]
    if doc.get("status") in RESOLVED_STATUSES:
        return doc.get("updated_at")
    return None


def _days_between(start: datetime, end: datetime) -> float:
    return max(0.0, round((end - start).total_seconds() / 86400.0, 1))


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


async def overview(
    db: AsyncIOMotorDatabase,
    actor: UserPublic,
    *,
    period_days: int = DEFAULT_PERIOD_DAYS,
) -> OverviewResponse:
    """KPIs, daily trend and category mix, scoped to the caller."""
    query, scope, ward = _scope(actor)
    projection = {
        "status": 1,
        "category": 1,
        "ward": 1,
        "created_at": 1,
        "resolved_at": 1,
        "closed_at": 1,
        "updated_at": 1,
        "sla": 1,
    }
    docs = [doc async for doc in db["complaints"].find(query, projection)]
    now = datetime.now(UTC)
    week_ago = now - timedelta(days=7)
    period_start = (now - timedelta(days=period_days - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    open_items = [doc for doc in docs if doc.get("status") in OPEN_STATUSES]
    resolved = [
        (doc, _resolved_at(doc))
        for doc in docs
        if doc.get("status") in RESOLVED_STATUSES and _resolved_at(doc) is not None
    ]
    resolution_days = [
        _days_between(doc["created_at"], finished)
        for doc, finished in resolved
        if finished is not None and finished >= period_start
    ]
    open_breaches = sum(
        1
        for doc in open_items
        if (doc.get("sla") or {}).get("breached")
        or (
            (doc.get("sla") or {}).get("due_at") is not None
            and doc["sla"]["due_at"] < now
        )
    )

    kpis = KpiSummary(
        open=len(open_items),
        resolved_this_week=sum(1 for _, finished in resolved if finished and finished >= week_ago),
        avg_resolution_days=_mean(resolution_days),
        sla_breaches=open_breaches,
        total=len(docs),
        resolved_rate=round(len(resolved) / len(docs), 4) if docs else 0.0,
    )

    received_by_day: dict[Any, int] = defaultdict(int)
    resolved_by_day: dict[Any, int] = defaultdict(int)
    category_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"count": 0, "open": 0, "resolved": 0}
    )
    for doc in docs:
        if doc["created_at"] >= period_start:
            day = doc["created_at"].date()
            received_by_day[day] += 1
            bucket = category_counts[str(doc["category"])]
            bucket["count"] += 1
            if doc.get("status") in OPEN_STATUSES:
                bucket["open"] += 1
            elif doc.get("status") in RESOLVED_STATUSES:
                bucket["resolved"] += 1
        finished = _resolved_at(doc)
        if finished is not None and finished >= period_start:
            resolved_by_day[finished.date()] += 1

    trend: list[TrendPoint] = []
    for offset in range(period_days):
        day = (period_start + timedelta(days=offset)).date()
        trend.append(
            TrendPoint(
                date=day,
                received=received_by_day.get(day, 0),
                resolved=resolved_by_day.get(day, 0),
            )
        )

    period_total = sum(bucket["count"] for bucket in category_counts.values())
    categories = [
        CategoryStat(
            category=category,  # type: ignore[arg-type]
            count=bucket["count"],
            open=bucket["open"],
            resolved=bucket["resolved"],
            share=round(bucket["count"] / period_total, 4) if period_total else 0.0,
        )
        for category, bucket in sorted(
            category_counts.items(), key=lambda item: item[1]["count"], reverse=True
        )
    ]

    return OverviewResponse(
        generated_at=now,
        period_days=period_days,
        scope=scope,  # type: ignore[arg-type]
        ward=ward,
        kpis=kpis,
        trend=trend,
        categories=categories,
    )


async def complaint_map(
    db: AsyncIOMotorDatabase,
    actor: UserPublic,
    *,
    category: str | None = None,
    status: ComplaintStatus | None = None,
    ward: int | None = None,
    limit: int = 1500,
) -> ComplaintMapResponse:
    """Lightweight map points with the same role scope as the dashboard."""
    scope_query, scope, scoped_ward = _scope(actor)
    query: dict[str, Any] = dict(scope_query)
    if category:
        query["category"] = category
    if status:
        query["status"] = status.value
    if ward is not None:
        query["ward"] = ward

    total = await db["complaints"].count_documents(query)
    projection = {
        "title": 1,
        "category": 1,
        "status": 1,
        "severity": 1,
        "ward": 1,
        "priority.score": 1,
        "location": 1,
        "created_at": 1,
        "sla.due_at": 1,
    }
    cursor = (
        db["complaints"]
        .find(query, projection)
        .sort("priority.score", -1)
        .limit(limit)
    )
    items = [
        MapComplaint(
            id=str(doc["_id"]),
            title=doc["title"],
            category=doc["category"],
            status=doc["status"],
            severity=int(doc.get("severity", 3)),
            ward=doc.get("ward"),
            priority=(doc.get("priority") or {}).get("score"),
            location=doc["location"],
            created_at=doc["created_at"],
            due_at=(doc.get("sla") or {}).get("due_at"),
        )
        async for doc in cursor
    ]
    return ComplaintMapResponse(
        items=items,
        total=total,
        truncated=total > len(items),
        scope=scope,  # type: ignore[arg-type]
        ward=scoped_ward,
    )


async def public_stats(db: AsyncIOMotorDatabase) -> PublicStats:
    """Anonymised, all-ward statistics for the public transparency portal."""
    now = datetime.now(UTC)
    period_start = now - timedelta(days=PUBLIC_PERIOD_DAYS)
    projection = {
        "title": 1,
        "category": 1,
        "status": 1,
        "ward": 1,
        "created_at": 1,
        "resolved_at": 1,
        "closed_at": 1,
        "updated_at": 1,
        "sla": 1,
        "resolution.verification.passed": 1,
    }
    docs = [doc async for doc in db["complaints"].find({}, projection)]
    wards = {
        doc["ward_no"]: doc
        async for doc in db["wards"].find({}, {"ward_no": 1, "name": 1, "zone": 1})
    }

    open_items = [doc for doc in docs if doc.get("status") in OPEN_STATUSES]
    resolved_period = [
        (doc, finished)
        for doc in docs
        if doc.get("status") in RESOLVED_STATUSES
        and (finished := _resolved_at(doc)) is not None
        and finished >= period_start
    ]
    all_resolved = [
        (doc, finished)
        for doc in docs
        if doc.get("status") in RESOLVED_STATUSES and (finished := _resolved_at(doc)) is not None
    ]
    resolution_days = [
        _days_between(doc["created_at"], finished) for doc, finished in resolved_period
    ]
    open_breaches = sum(
        1
        for doc in open_items
        if (doc.get("sla") or {}).get("breached")
        or (
            (doc.get("sla") or {}).get("due_at") is not None
            and doc["sla"]["due_at"] < now
        )
    )
    totals = KpiSummary(
        open=len(open_items),
        resolved_this_week=sum(
            1 for _, finished in all_resolved if finished >= now - timedelta(days=7)
        ),
        avg_resolution_days=_mean(resolution_days),
        sla_breaches=open_breaches,
        total=len(docs),
        resolved_rate=round(len(all_resolved) / len(docs), 4) if docs else 0.0,
    )

    ward_stats: list[PublicWardStat] = []
    for ward_no in sorted(wards):
        ward_docs = [doc for doc in docs if doc.get("ward") == ward_no]
        ward_open = [doc for doc in ward_docs if doc.get("status") in OPEN_STATUSES]
        ward_resolved_period = [
            (doc, finished)
            for doc in ward_docs
            if doc.get("status") in RESOLVED_STATUSES
            and (finished := _resolved_at(doc)) is not None
            and finished >= period_start
        ]
        ward_resolved_all = [
            doc for doc in ward_docs if doc.get("status") in RESOLVED_STATUSES
        ]
        breached = sum(
            1
            for doc, _ in ward_resolved_period
            if (doc.get("sla") or {}).get("breached")
        )
        ward_days = [
            _days_between(doc["created_at"], finished)
            for doc, finished in ward_resolved_period
        ]
        ward_stats.append(
            PublicWardStat(
                ward=ward_no,
                name=wards[ward_no].get("name", f"Ward {ward_no}"),
                zone=wards[ward_no].get("zone", ""),
                total=len(ward_docs),
                open=len(ward_open),
                resolved=len(ward_resolved_period),
                avg_resolution_days=_mean(ward_days),
                sla_compliance=(
                    round(1 - breached / len(ward_resolved_period), 4)
                    if ward_resolved_period
                    else 1.0
                ),
                resolved_rate=(
                    round(len(ward_resolved_all) / len(ward_docs), 4) if ward_docs else 0.0
                ),
            )
        )

    category_buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "resolved": 0})
    for doc in docs:
        if doc["created_at"] < period_start:
            continue
        bucket = category_buckets[str(doc["category"])]
        bucket["total"] += 1
        if doc.get("status") in RESOLVED_STATUSES:
            bucket["resolved"] += 1
    period_total = sum(bucket["total"] for bucket in category_buckets.values())
    categories = [
        PublicCategoryStat(
            category=category,  # type: ignore[arg-type]
            total=bucket["total"],
            resolved=bucket["resolved"],
            share=round(bucket["total"] / period_total, 4) if period_total else 0.0,
        )
        for category, bucket in sorted(
            category_buckets.items(), key=lambda item: item[1]["total"], reverse=True
        )
    ]

    recent = sorted(
        resolved_period, key=lambda item: item[1], reverse=True
    )[:8]
    recent_resolutions = [
        PublicResolution(
            title=doc["title"],
            category=doc["category"],
            ward=doc.get("ward"),
            ward_name=wards.get(doc.get("ward"), {}).get("name"),
            resolved_at=finished,
            resolution_days=_days_between(doc["created_at"], finished),
            verified=bool(
                ((doc.get("resolution") or {}).get("verification") or {}).get("passed")
            ),
        )
        for doc, finished in recent
    ]

    return PublicStats(
        generated_at=now,
        period_days=PUBLIC_PERIOD_DAYS,
        totals=totals,
        resolved_in_period=len(resolved_period),
        wards=ward_stats,
        categories=categories,
        recent_resolutions=recent_resolutions,
    )
