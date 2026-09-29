"""Benchmark the local route-planning hot path without making external requests."""

# Django must be initialized before importing application modules.
# ruff: noqa: E402

from __future__ import annotations

import json
import os
import sys
from decimal import Decimal
from time import perf_counter

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import django

django.setup()

from apps.routing.domain import Coordinate, RouteResult
from apps.routing.fuel import FuelStopOptimizer
from apps.routing.matching import RouteCorridorMatcher, StationRecord
from apps.routing.planning import RoutePlanningService
from apps.routing.services import RouteService
from apps.stations.geocoding import GeocodeResult, GeocodeStatus


class CachedGeocoder:
    calls = 0

    def geocode_location(self, query: str) -> tuple[GeocodeResult, bool]:
        locations = {
            "benchmark start": (35.0, -100.0),
            "benchmark destination": (35.0, -90.0),
        }
        latitude, longitude = locations[query]
        return GeocodeResult(GeocodeStatus.SUCCESS, latitude, longitude, query), True


class CountingRouteProvider:
    calls = 0

    def __init__(self, route: RouteResult) -> None:
        self.route_result = route

    def route(self, start: Coordinate, destination: Coordinate, *, profile: str, options=None):
        self.calls += 1
        return self.route_result


class BoundedRepository:
    def __init__(self, stations: list[StationRecord]) -> None:
        self.stations = stations
        self.rows_after_bounds = 0

    def candidates(self, bounds=None):
        if bounds is None:
            selected = self.stations
        else:
            min_lat, max_lat, min_lon, max_lon = bounds
            selected = [
                station
                for station in self.stations
                if min_lat <= station.latitude <= max_lat
                and min_lon <= station.longitude <= max_lon
            ]
        self.rows_after_bounds = len(selected)
        return iter(selected)


class TimedOptimizer(FuelStopOptimizer):
    elapsed_ms = 0.0
    candidate_count = 0

    def optimize(self, route, stations):
        self.candidate_count = len(stations)
        started = perf_counter()
        result = super().optimize(route, stations)
        self.elapsed_ms = (perf_counter() - started) * 1000
        return result


def main() -> None:
    coordinates = [[-100.0 + (10.0 * index / 100), 35.0] for index in range(101)]
    route = RouteResult(
        distance_meters=568.0 * 1609.344,
        duration_seconds=8 * 3600,
        geometry={"type": "LineString", "coordinates": coordinates},
        provider="benchmark",
        profile="driving",
    )
    stations: list[StationRecord] = []
    for index in range(6738):
        if index < 1238:
            longitude = -100.0 + (9.9 * index / 1238)
            latitude = 35.0 + (0.5 if index % 2 else -0.5) / 69.093
        else:
            longitude = -125.0 + ((index * 17) % 3000) / 100
            latitude = 25.0 + ((index * 19) % 2000) / 100
        stations.append(
            StationRecord(
                station_id=f"station-{index}",
                name=f"Station {index}",
                latitude=latitude,
                longitude=longitude,
                price=Decimal("3.00") + Decimal(index % 100) / 100,
            )
        )

    repository = BoundedRepository(stations)
    provider = CountingRouteProvider(route)
    optimizer = TimedOptimizer()
    planner = RoutePlanningService(
        geocoder=CachedGeocoder(),
        route_service=RouteService(provider, cache_ttl_seconds=300),
        station_repository=repository,
        matcher=RouteCorridorMatcher(max_distance_miles=5.0),
        optimizer=optimizer,
    )
    started = perf_counter()
    planner.plan("benchmark start", "benchmark destination")
    response_ms = (perf_counter() - started) * 1000
    print(
        json.dumps(
            {
                "response_ms": round(response_ms, 2),
                "external_geocoder_calls": CachedGeocoder.calls,
                "external_routing_calls": provider.calls,
                "station_rows_before_bounds": len(stations),
                "station_rows_after_bounds": repository.rows_after_bounds,
                "matched_station_count": optimizer.candidate_count,
                "optimizer_ms": round(optimizer.elapsed_ms, 2),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
