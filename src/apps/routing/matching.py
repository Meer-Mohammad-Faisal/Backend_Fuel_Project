from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import asin, cos, isfinite, radians, sin, sqrt
from typing import Any

from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

from apps.routing.domain import RouteResult

MILES_PER_DEGREE_LATITUDE = 69.093
EARTH_RADIUS_MILES = 3958.7613


@dataclass(frozen=True)
class StationRecord:
    """Small domain representation accepted by the matcher."""

    station_id: str
    name: str
    latitude: float
    longitude: float
    price: Any
    source_opis_id: str = ""
    city: str = ""
    state: str = ""

    @classmethod
    def from_model(cls, station: Any) -> StationRecord:
        if station.latitude is None or station.longitude is None:
            raise ValueError("station must have latitude and longitude")
        return cls(
            station_id=str(station.station_id),
            name=station.name,
            latitude=float(station.latitude),
            longitude=float(station.longitude),
            price=station.retail_price,
            source_opis_id=station.source_opis_id,
            city=station.city,
            state=station.state,
        )


@dataclass(frozen=True)
class MatchedStation:
    station_id: str
    name: str
    latitude: float
    longitude: float
    price: Any
    distance_along_route_miles: float
    distance_from_route_miles: float
    source_opis_id: str = ""
    city: str = ""
    state: str = ""


@dataclass(frozen=True)
class _RouteSegment:
    start: tuple[float, float]
    end: tuple[float, float]
    length_miles: float
    cumulative_start_miles: float
    midpoint_latitude: float


class RouteCorridorMatcher:
    """Match stations to a route using indexed corridor search and local projection."""

    def __init__(
        self,
        *,
        max_distance_miles: float = 5.0,
        duplicate_coordinate_tolerance_miles: float = 0.05,
    ) -> None:
        if max_distance_miles <= 0:
            raise ValueError("max_distance_miles must be positive")
        if duplicate_coordinate_tolerance_miles < 0:
            raise ValueError("duplicate_coordinate_tolerance_miles cannot be negative")
        self.max_distance_miles = max_distance_miles
        self.duplicate_coordinate_tolerance_miles = duplicate_coordinate_tolerance_miles

    def match(
        self,
        route: RouteResult | dict[str, Any],
        stations: list[StationRecord] | tuple[StationRecord, ...],
    ) -> list[MatchedStation]:
        geometry = route.geometry if isinstance(route, RouteResult) else route
        coordinates = self._coordinates_from_geometry(geometry)
        segments = self._build_segments(coordinates)
        if not segments:
            return []

        route_index = self._build_index(segments)
        matched: list[MatchedStation] = []
        for station in stations:
            if not self._valid_station(station):
                continue
            candidate = self._match_station(station, segments, route_index)
            if candidate is not None:
                matched.append(candidate)

        matched.sort(
            key=lambda item: (
                item.distance_along_route_miles,
                item.distance_from_route_miles,
                item.station_id,
            )
        )
        return self._remove_redundant_duplicates(matched)

    def candidate_bounds(
        self, route: RouteResult | dict[str, Any]
    ) -> tuple[float, float, float, float]:
        """Return a conservative lat/lon bounding box for database prefiltering."""
        geometry = route.geometry if isinstance(route, RouteResult) else route
        coordinates = self._coordinates_from_geometry(geometry)
        latitudes = [point[0] for point in coordinates]
        longitudes = [point[1] for point in coordinates]
        minimum_cosine = max(
            0.01,
            min(cos(radians(abs(latitude))) for latitude in latitudes),
        )
        latitude_padding = self.max_distance_miles / MILES_PER_DEGREE_LATITUDE
        longitude_padding = latitude_padding / minimum_cosine
        return (
            min(latitudes) - latitude_padding,
            max(latitudes) + latitude_padding,
            min(longitudes) - longitude_padding,
            max(longitudes) + longitude_padding,
        )

    def _match_station(
        self,
        station: StationRecord,
        segments: list[_RouteSegment],
        route_index: STRtree,
    ) -> MatchedStation | None:
        reference_latitude = self._index_reference_latitude(segments)
        point = Point(*self._global_xy(station.latitude, station.longitude, reference_latitude))
        search_radius = self.max_distance_miles * 2.0
        segment_indexes = route_index.query(point.buffer(search_radius))
        best: tuple[float, float, int] | None = None
        best_raw_t = 0.0

        for raw_index in segment_indexes:
            index = int(raw_index)
            segment = segments[index]
            distance, raw_t = self._project_to_segment(station, segment)
            if distance > self.max_distance_miles:
                continue
            projected_t = min(1.0, max(0.0, raw_t))
            route_distance = segment.cumulative_start_miles + projected_t * segment.length_miles
            candidate_key = (distance, route_distance, index)
            if best is None or candidate_key < best:
                best = candidate_key
                best_raw_t = raw_t

        if best is None:
            return None
        segment_index = best[2]
        if segment_index == 0 and best_raw_t < 0:
            return None
        if segment_index == len(segments) - 1 and best_raw_t > 1:
            return None

        return MatchedStation(
            station_id=station.station_id,
            name=station.name,
            latitude=station.latitude,
            longitude=station.longitude,
            price=station.price,
            distance_along_route_miles=best[1],
            distance_from_route_miles=best[0],
            source_opis_id=station.source_opis_id,
            city=station.city,
            state=station.state,
        )

    def _build_index(self, segments: list[_RouteSegment]) -> STRtree:
        reference_latitude = self._index_reference_latitude(segments)
        geometries = [
            LineString(
                [
                    self._global_xy(segment.start[0], segment.start[1], reference_latitude),
                    self._global_xy(segment.end[0], segment.end[1], reference_latitude),
                ]
            )
            for segment in segments
        ]
        return STRtree(geometries)

    @staticmethod
    def _coordinates_from_geometry(geometry: dict[str, Any]) -> list[tuple[float, float]]:
        if geometry.get("type") != "LineString":
            raise ValueError("route geometry must be a GeoJSON LineString")
        raw_coordinates = geometry.get("coordinates")
        if not isinstance(raw_coordinates, list) or len(raw_coordinates) < 2:
            raise ValueError("route geometry must contain at least two coordinates")
        coordinates: list[tuple[float, float]] = []
        for point in raw_coordinates:
            if (
                not isinstance(point, list)
                or len(point) < 2
                or not isinstance(point[0], (int, float))
                or not isinstance(point[1], (int, float))
            ):
                raise ValueError("route geometry contains an invalid coordinate")
            coordinates.append((float(point[1]), float(point[0])))
        return coordinates

    @staticmethod
    def _build_segments(coordinates: list[tuple[float, float]]) -> list[_RouteSegment]:
        segments: list[_RouteSegment] = []
        cumulative = 0.0
        for start, end in zip(coordinates, coordinates[1:], strict=False):
            length = _haversine_miles(start[0], start[1], end[0], end[1])
            if length == 0:
                continue
            segments.append(
                _RouteSegment(
                    start=start,
                    end=end,
                    length_miles=length,
                    cumulative_start_miles=cumulative,
                    midpoint_latitude=(start[0] + end[0]) / 2,
                )
            )
            cumulative += length
        return segments

    @staticmethod
    def _index_reference_latitude(segments: list[_RouteSegment]) -> float:
        return sum(segment.midpoint_latitude for segment in segments) / len(segments)

    @staticmethod
    def _global_xy(
        latitude: float,
        longitude: float,
        reference_latitude: float,
    ) -> tuple[float, float]:
        x = longitude * MILES_PER_DEGREE_LATITUDE * cos(radians(reference_latitude))
        y = latitude * MILES_PER_DEGREE_LATITUDE
        return x, y

    @staticmethod
    def _project_to_segment(
        station: StationRecord,
        segment: _RouteSegment,
    ) -> tuple[float, float]:
        reference_latitude = segment.midpoint_latitude
        start_x, start_y = RouteCorridorMatcher._local_xy(
            segment.start[0], segment.start[1], reference_latitude
        )
        end_x, end_y = RouteCorridorMatcher._local_xy(
            segment.end[0], segment.end[1], reference_latitude
        )
        point_x, point_y = RouteCorridorMatcher._local_xy(
            station.latitude, station.longitude, reference_latitude
        )
        vector_x = end_x - start_x
        vector_y = end_y - start_y
        denominator = vector_x * vector_x + vector_y * vector_y
        raw_t = ((point_x - start_x) * vector_x + (point_y - start_y) * vector_y) / denominator
        projected_t = min(1.0, max(0.0, raw_t))
        projected_x = start_x + projected_t * vector_x
        projected_y = start_y + projected_t * vector_y
        return sqrt((point_x - projected_x) ** 2 + (point_y - projected_y) ** 2), raw_t

    @staticmethod
    def _local_xy(
        latitude: float,
        longitude: float,
        reference_latitude: float,
    ) -> tuple[float, float]:
        x = longitude * MILES_PER_DEGREE_LATITUDE * cos(radians(reference_latitude))
        y = latitude * MILES_PER_DEGREE_LATITUDE
        return x, y

    def _remove_redundant_duplicates(
        self,
        candidates: list[MatchedStation],
    ) -> list[MatchedStation]:
        retained: list[MatchedStation] = []
        active: deque[tuple[int, MatchedStation]] = deque()
        for candidate in candidates:
            while active and (
                candidate.distance_along_route_miles
                - active[0][1].distance_along_route_miles
                > self.duplicate_coordinate_tolerance_miles
            ):
                active.popleft()
            duplicate_index = next(
                (
                    index
                    for index, existing in active
                    if _haversine_miles(
                        candidate.latitude,
                        candidate.longitude,
                        existing.latitude,
                        existing.longitude,
                    )
                    <= self.duplicate_coordinate_tolerance_miles
                ),
                None,
            )
            if duplicate_index is None:
                index = len(retained)
                retained.append(candidate)
                active.append((index, candidate))
                continue
            existing = retained[duplicate_index]
            if (candidate.price, candidate.station_id) < (existing.price, existing.station_id):
                retained[duplicate_index] = candidate
                for position, (index, _) in enumerate(active):
                    if index == duplicate_index:
                        active[position] = (index, candidate)
                        break
        return retained

    @staticmethod
    def _valid_station(station: StationRecord) -> bool:
        try:
            price = float(station.price)
        except (TypeError, ValueError):
            return False
        return (
            isfinite(station.latitude)
            and isfinite(station.longitude)
            and -90 <= station.latitude <= 90
            and -180 <= station.longitude <= 180
            and isfinite(price)
            and price > 0
        )


def _haversine_miles(
    latitude_one: float,
    longitude_one: float,
    latitude_two: float,
    longitude_two: float,
) -> float:
    latitude_delta = radians(latitude_two - latitude_one)
    longitude_delta = radians(longitude_two - longitude_one)
    a = (
        sin(latitude_delta / 2) ** 2
        + cos(radians(latitude_one))
        * cos(radians(latitude_two))
        * sin(longitude_delta / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * asin(sqrt(a))
