"""Helpers shared by Phase-2 tests."""

from __future__ import annotations

from typing import Any

# Ward 1 (Jayanagar) polygon spans lng 77.484..77.516, lat 12.887..12.923.
WARD1_LNG, WARD1_LAT = 77.500, 12.905
WARD2_LNG, WARD2_LAT = 77.536, 12.905


def complaint_payload(**overrides: Any) -> dict[str, Any]:
    """Valid complaint payload centred in Ward 1."""
    payload: dict[str, Any] = {
        "title": "Deep pothole near the bus stop",
        "description": (
            "A large pothole has formed near the bus stop after the rains. "
            "Two-wheelers are skidding and it is dangerous at night."
        ),
        "category": "roads",
        "severity": 4,
        "location": {"type": "Point", "coordinates": [WARD1_LNG, WARD1_LAT]},
        "address": "10th Main Road, Jayanagar, Bengaluru",
        "landmark": "Near bus stop",
    }
    payload.update(overrides)
    return payload
