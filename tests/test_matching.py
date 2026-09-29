from __future__ import annotations

from decimal import Decimal

from django.test import SimpleTestCase

from apps.routing.domain import RouteResult
from apps.routing.matching import RouteCorridorMatcher, StationRecord


def route(coordinates: list[list[float]]) -> RouteResult:
    return RouteResult(
        distance_meters=10_000_000,
        duration_seconds=3_600,
        geometry={"type": "LineString", "coordinates": coordinates},
        provider="test",
        profile="driving",
    )


def station(
    station_id: str,
    latitude: float,
    longitude: float,
    price: str = "3.50",
) -> StationRecord:
    return StationRecord(
        station_id=station_id,
        name=f"Station {station_id}",
        latitude=latitude,
        longitude=longitude,
        price=Decimal(price),
    )


class RouteCorridorMatcherTests(SimpleTestCase):
    def setUp(self) -> None:
        self.matcher = RouteCorridorMatcher(max_distance_miles=5)
        self.horizontal_route = route([[-80.0, 35.0], [-79.0, 35.0]])

    def test_station_directly_on_route_is_projected(self) -> None:
        matches = self.matcher.match(self.horizontal_route, [station("on", 35.0, -79.5)])

        self.assertEqual([item.station_id for item in matches], ["on"])
        self.assertAlmostEqual(matches[0].distance_from_route_miles, 0, places=5)
        self.assertAlmostEqual(matches[0].distance_along_route_miles, 28.7, delta=0.5)

    def test_station_near_route_is_accepted_with_distance(self) -> None:
        matches = self.matcher.match(
            self.horizontal_route,
            [station("near", 35.0 + 2 / 69.093, -79.5)],
        )

        self.assertEqual(len(matches), 1)
        self.assertAlmostEqual(matches[0].distance_from_route_miles, 2, delta=0.05)

    def test_station_far_from_route_is_rejected(self) -> None:
        matches = self.matcher.match(
            self.horizontal_route,
            [station("far", 35.0 + 10 / 69.093, -79.5)],
        )

        self.assertEqual(matches, [])

    def test_station_before_start_and_after_destination_are_rejected(self) -> None:
        matches = self.matcher.match(
            self.horizontal_route,
            [station("before", 35.0, -80.02), station("after", 35.0, -78.98)],
        )

        self.assertEqual(matches, [])

    def test_identical_coordinates_keep_the_cheapest_station(self) -> None:
        matches = self.matcher.match(
            self.horizontal_route,
            [
                station("expensive", 35.0, -79.5, "4.00"),
                station("cheap", 35.0, -79.5, "3.00"),
            ],
        )

        self.assertEqual([item.station_id for item in matches], ["cheap"])

    def test_near_identical_coordinates_are_collapsed(self) -> None:
        matches = self.matcher.match(
            self.horizontal_route,
            [
                station("first", 35.0, -79.5, "3.00"),
                station("second", 35.0 + 0.01 / 69.093, -79.5, "3.50"),
            ],
        )

        self.assertEqual([item.station_id for item in matches], ["first"])

    def test_multiple_segments_use_the_correct_segment(self) -> None:
        route_geometry = route([[-80.0, 35.0], [-79.0, 35.0], [-79.0, 36.0]])
        matches = self.matcher.match(route_geometry, [station("turn", 35.5, -79.0)])

        self.assertEqual(len(matches), 1)
        self.assertGreater(matches[0].distance_along_route_miles, 28)
        self.assertAlmostEqual(matches[0].distance_from_route_miles, 0, places=5)

    def test_long_route_is_matched(self) -> None:
        coordinates = [[-100.0 + index * 0.01, 35.0] for index in range(1_001)]
        long_route = route(coordinates)

        matches = self.matcher.match(long_route, [station("long", 35.0, -95.0)])

        self.assertEqual([item.station_id for item in matches], ["long"])
        self.assertGreater(matches[0].distance_along_route_miles, 250)

    def test_non_finite_station_price_is_rejected(self) -> None:
        matches = self.matcher.match(
            self.horizontal_route,
            [station("nan", 35.0, -79.5, "NaN")],
        )

        self.assertEqual(matches, [])
