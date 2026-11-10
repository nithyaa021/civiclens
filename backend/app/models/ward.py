"""Ward geography and sensitive-location models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

LAT_MIN, LAT_MAX = -90.0, 90.0
LNG_MIN, LNG_MAX = -180.0, 180.0


class GeoPoint(BaseModel):
    """GeoJSON point; ``coordinates`` is ``[longitude, latitude]``."""

    type: Literal["Point"] = Field(default="Point", description="GeoJSON geometry type.")
    coordinates: tuple[float, float] = Field(
        description="[longitude, latitude] in decimal degrees.",
        examples=[[77.5946, 12.9716]],
    )

    @field_validator("coordinates")
    @classmethod
    def _valid_coordinates(cls, value: tuple[float, float]) -> tuple[float, float]:
        lng, lat = value
        if not (LNG_MIN <= lng <= LNG_MAX):
            raise ValueError(f"longitude must be in [{LNG_MIN}, {LNG_MAX}]")
        if not (LAT_MIN <= lat <= LAT_MAX):
            raise ValueError(f"latitude must be in [{LAT_MIN}, {LAT_MAX}]")
        return value

    @property
    def lng(self) -> float:
        return self.coordinates[0]

    @property
    def lat(self) -> float:
        return self.coordinates[1]


class GeoPolygon(BaseModel):
    """GeoJSON polygon (first ring = exterior, closed)."""

    type: Literal["Polygon"] = Field(default="Polygon", description="GeoJSON geometry type.")
    coordinates: list[list[tuple[float, float]]] = Field(
        description="Rings of [lng, lat] vertices; the first ring is the exterior boundary.",
        examples=[[[[77.55, 12.90], [77.60, 12.90], [77.60, 12.95], [77.55, 12.90]]]],
    )

    @field_validator("coordinates")
    @classmethod
    def _rings_closed(
        cls, value: list[list[tuple[float, float]]]
    ) -> list[list[tuple[float, float]]]:
        if not value:
            raise ValueError("polygon needs at least one ring")
        for ring in value:
            if len(ring) < 4:
                raise ValueError("each ring needs at least 4 positions (closed)")
            if ring[0] != ring[-1]:
                raise ValueError("rings must be closed (first position == last)")
        return value


class SensitiveLocation(BaseModel):
    """A location whose proximity raises complaint priority (schools, hospitals)."""

    kind: Literal["school", "hospital"] = Field(description="Sensitive-site category.")
    name: str = Field(min_length=2, max_length=120, examples=["St. Mary's High School"])
    location: GeoPoint


class Ward(BaseModel):
    """Administrative ward with boundary polygon and sensitive sites."""

    ward_no: int = Field(ge=1, le=999, examples=[12])
    name: str = Field(min_length=2, max_length=80, examples=["Jayanagar"])
    zone: str = Field(min_length=2, max_length=80, examples=["South Zone"])
    polygon: GeoPolygon
    sensitive_locations: list[SensitiveLocation] = Field(default_factory=list)


class WardPublic(BaseModel):
    """Ward representation returned by the API (geometry included for maps)."""

    ward_no: int = Field(examples=[12])
    name: str = Field(examples=["Jayanagar"])
    zone: str = Field(examples=["South Zone"])
    centroid: GeoPoint = Field(description="Polygon centroid, used for map markers.")
    geometry: GeoPolygon = Field(description="Ward boundary ring (closed GeoJSON polygon).")
    sensitive_locations: list[SensitiveLocation] = Field(default_factory=list)
    complaint_count: int = Field(default=0, description="Open complaints in this ward.")
