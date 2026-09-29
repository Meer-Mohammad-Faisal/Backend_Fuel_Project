from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import isfinite

from apps.routing.domain import Coordinate, RouteResult
from apps.routing.fuel import FuelOptimizationResult, FuelStopOptimizer
from apps.routing.matching import RouteCorridorMatcher
from apps.routing.services import RouteService, configured_route_service
from apps.stations.geocoding import (
    GeocodeStatus,
    GeocodingService,
    configured_nominatim_geocoder,
)
from apps.stations.repositories import StationRepository


class LocationNotFoundError(Exception):
    """A requested user location could not be geocoded."""


@dataclass(frozen=True)
class GeocodedLocation:
    query: str
    latitude: float
    longitude: float
    display_name: str


@dataclass(frozen=True)
class RoutePlan:
    start: GeocodedLocation
    destination: GeocodedLocation
    route: RouteResult
    fuel: FuelOptimizationResult


class RoutePlanningService:
    """Application orchestration for one complete route/fuel plan."""

    def __init__(
        self,
        *,
        geocoder: GeocodingService,
        route_service: RouteService,
        station_repository: StationRepository,
        matcher: RouteCorridorMatcher,
        optimizer: FuelStopOptimizer,
    ) -> None:
        self.geocoder = geocoder
        self.route_service = route_service
        self.station_repository = station_repository
        self.matcher = matcher
        self.optimizer = optimizer

    def plan(self, start_query: str, destination_query: str) -> RoutePlan:
        start = self._geocode(start_query, "start")
        destination = self._geocode(destination_query, "destination")
        route = self.route_service.calculate(
            Coordinate(start.latitude, start.longitude),
            Coordinate(destination.latitude, destination.longitude),
        )
        bounds = self.matcher.candidate_bounds(route)
        candidates = self.matcher.match(
            route, list(self.station_repository.candidates(bounds))
        )
        fuel = self.optimizer.optimize(route, candidates)
        return RoutePlan(start=start, destination=destination, route=route, fuel=fuel)

    def _geocode(self, query: str, label: str) -> GeocodedLocation:
        result, _ = self.geocoder.geocode_location(query)
        if (
            result.status != GeocodeStatus.SUCCESS
            or result.latitude is None
            or result.longitude is None
            or not isfinite(result.latitude)
            or not isfinite(result.longitude)
            or not -90 <= result.latitude <= 90
            or not -180 <= result.longitude <= 180
        ):
            raise LocationNotFoundError(f"Unable to geocode {label} location")
        return GeocodedLocation(
            query=query,
            latitude=result.latitude,
            longitude=result.longitude,
            display_name=result.display_name,
        )


@lru_cache(maxsize=1)
def configured_route_planning_service() -> RoutePlanningService:
    return RoutePlanningService(
        geocoder=GeocodingService(configured_nominatim_geocoder()),
        route_service=configured_route_service(),
        station_repository=StationRepository(),
        matcher=RouteCorridorMatcher(),
        optimizer=FuelStopOptimizer(),
    )
