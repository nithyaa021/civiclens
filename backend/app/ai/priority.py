"""Transparent weighted priority scoring.

Every complaint stores its full score breakdown so the UI can explain
exactly why an issue is ranked where it is:

    score = 100 * sum(weight_c * normalized_c)   for each component c

Components (all normalised to [0, 1]):
- severity            : citizen-provided 1..5 -> (s - 1) / 4
- frequency           : upvotes on the complaint, capped at VOTES_FOR_MAX
- cluster_density     : recurring-issue cluster size, capped at CLUSTER_CAP
- age_unresolved      : days since reporting (frozen at resolution), capped
- sensitive_proximity : inverse distance to the nearest school/hospital
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.models.complaint import PriorityComponent, PriorityScore

VOTES_FOR_MAX = 10.0
CLUSTER_CAP = 10.0


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def compute_priority(
    *,
    severity: int,
    votes: int,
    cluster_count: int,
    created_at: datetime,
    resolved_at: datetime | None,
    now: datetime | None,
    nearest_sensitive_km: float | None,
    weights: dict[str, float],
    sensitive_radius_km: float,
    max_age_days: float,
) -> PriorityScore:
    """Compute the priority score and its per-component breakdown."""
    now = now or datetime.now(UTC)
    end = resolved_at or now
    days_unresolved = max(0.0, (end - created_at).total_seconds() / 86400.0)

    normalized: dict[str, tuple[float, float]] = {}
    normalized["severity"] = ((severity - 1) / 4.0, float(severity))
    normalized["frequency"] = (_clamp01(votes / VOTES_FOR_MAX), float(votes))
    normalized["cluster_density"] = (_clamp01(cluster_count / CLUSTER_CAP), float(cluster_count))
    normalized["age_unresolved"] = (_clamp01(days_unresolved / max_age_days), days_unresolved)
    if nearest_sensitive_km is None:
        # No school/hospital within the configured radius: zero contribution,
        # raw value reported as the radius cap so the UI can say "none nearby".
        normalized["sensitive_proximity"] = (0.0, sensitive_radius_km)
    else:
        normalized["sensitive_proximity"] = (
            _clamp01(1.0 - nearest_sensitive_km / sensitive_radius_km),
            nearest_sensitive_km,
        )

    components: dict[str, PriorityComponent] = {}
    total = 0.0
    for name, weight in weights.items():
        norm, raw = normalized[name]
        contribution = norm * weight * 100.0
        total += contribution
        components[name] = PriorityComponent(
            raw=round(raw, 4),
            normalized=round(norm, 6),
            weight=round(weight, 4),
            contribution=round(contribution, 4),
        )

    formula = (
        "score = 100 * ("
        + " + ".join(f"{weights[name]:.2f}*{name}" for name in weights)
        + "), each term normalised to 0-1"
    )
    return PriorityScore(
        score=round(total, 2),
        components=components,
        formula=formula,
        computed_at=now,
    )
