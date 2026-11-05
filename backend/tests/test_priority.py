"""Priority scoring: the stored breakdown must explain the score exactly."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.ai.priority import CLUSTER_CAP, VOTES_FOR_MAX, compute_priority
from app.core.config import get_settings

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
WEIGHTS = get_settings().priority_weights


def score(**overrides) -> float:  # noqa: ANN003
    kwargs = {
        "severity": 3,
        "votes": 0,
        "cluster_count": 0,
        "created_at": NOW - timedelta(days=2),
        "resolved_at": None,
        "now": NOW,
        "nearest_sensitive_km": None,
        "weights": WEIGHTS,
        "sensitive_radius_km": 1.0,
        "max_age_days": 30.0,
    }
    kwargs.update(overrides)
    return compute_priority(**kwargs).score


def test_breakdown_components_sum_to_score() -> None:
    result = compute_priority(
        severity=5,
        votes=4,
        cluster_count=6,
        created_at=NOW - timedelta(days=10),
        resolved_at=None,
        now=NOW,
        nearest_sensitive_km=0.2,
        weights=WEIGHTS,
        sensitive_radius_km=1.0,
        max_age_days=30.0,
    )
    assert 0.0 <= result.score <= 100.0
    assert set(result.components) == set(WEIGHTS)
    total = sum(component.contribution for component in result.components.values())
    assert result.score == pytest.approx(total, abs=0.05)
    for name, component in result.components.items():
        assert component.weight == pytest.approx(WEIGHTS[name], abs=0.001)
        assert 0.0 <= component.normalized <= 1.0
        assert component.contribution == pytest.approx(
            component.normalized * component.weight * 100.0, abs=0.01
        )
    formula = result.formula
    assert all(name in formula for name in WEIGHTS)


def test_score_is_monotonic_in_each_signal() -> None:
    base = score(severity=1)
    assert score(severity=5) > base
    # severity spans exactly its 0.30 weight x 100 points.
    assert score(severity=5) - score(severity=1) == pytest.approx(30.0, abs=0.01)

    assert score(votes=5) > score(votes=0)
    assert score(cluster_count=5) > score(cluster_count=0)
    assert score(created_at=NOW - timedelta(days=20)) > score(created_at=NOW)
    assert score(nearest_sensitive_km=0.1) > score(nearest_sensitive_km=0.9)
    assert score(nearest_sensitive_km=0.1) > score(nearest_sensitive_km=None)


def test_signals_are_capped() -> None:
    assert score(votes=int(VOTES_FOR_MAX)) == score(votes=1_000)
    assert score(cluster_count=int(CLUSTER_CAP)) == score(cluster_count=1_000)
    # Age stops counting after the configured window.
    saturated = score(created_at=NOW - timedelta(days=30))
    assert saturated == score(created_at=NOW - timedelta(days=900))


def test_resolution_freezes_the_age_component() -> None:
    created = NOW - timedelta(days=20)
    resolved = NOW - timedelta(days=5)
    frozen = compute_priority(
        severity=3,
        votes=0,
        cluster_count=0,
        created_at=created,
        resolved_at=resolved,
        now=NOW,
        nearest_sensitive_km=None,
        weights=WEIGHTS,
        sensitive_radius_km=1.0,
        max_age_days=30.0,
    )
    five_days_later = compute_priority(
        severity=3,
        votes=0,
        cluster_count=0,
        created_at=created,
        resolved_at=resolved,
        now=NOW + timedelta(days=5),
        nearest_sensitive_km=None,
        weights=WEIGHTS,
        sensitive_radius_km=1.0,
        max_age_days=30.0,
    )
    assert frozen.score == five_days_later.score
    assert frozen.components["age_unresolved"].raw == pytest.approx(15.0, abs=0.01)
