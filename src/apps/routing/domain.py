from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any


class RoutingError(Exception):
    """Base class for safe, user-facing routing failures."""


class RoutingProviderError(RoutingError):
    """The provider could not complete a route request."""


class MalformedRoutingResponse(RoutingError):
    """The provider response did not satisfy the normalized route contract."""


@dataclass(frozen=True)
class Coordinate:
    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if not isfinite(self.latitude) or not -90 <= self.latitude <= 90:
            raise ValueError("latitude must be between -90 and 90")
        if not isfinite(self.longitude) or not -180 <= self.longitude <= 180:
            raise ValueError("longitude must be between -180 and 180")


@dataclass(frozen=True)
class RouteResult:
    distance_meters: float
    duration_seconds: float
    geometry: dict[str, Any]
    provider: str
    profile: str

    @property
    def distance_miles(self) -> float:
        return self.distance_meters / 1609.344

    def as_cache_value(self) -> dict[str, Any]:
        return {
            "distance_meters": self.distance_meters,
            "duration_seconds": self.duration_seconds,
            "geometry": self.geometry,
            "provider": self.provider,
            "profile": self.profile,
        }

    @classmethod
    def from_cache_value(cls, value: dict[str, Any]) -> RouteResult:
        return cls(
            distance_meters=float(value["distance_meters"]),
            duration_seconds=float(value["duration_seconds"]),
            geometry=value["geometry"],
            provider=str(value["provider"]),
            profile=str(value["profile"]),
        )
