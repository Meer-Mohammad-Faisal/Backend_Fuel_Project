from __future__ import annotations

import unittest
from decimal import Decimal
from math import inf

from apps.routing.domain import RouteResult
from apps.routing.fuel import FuelOptimizationError, FuelOptimizerConfig, FuelStopOptimizer
from apps.routing.matching import MatchedStation


def route(distance_miles: float) -> RouteResult:
    return RouteResult(
        distance_meters=distance_miles * 1609.344,
        duration_seconds=1,
        geometry={"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
        provider="test",
        profile="driving",
    )


def station(
    station_id: str,
    position: float,
    price: str,
    *,
    city: str = "Test City",
    state: str = "TX",
) -> MatchedStation:
    return MatchedStation(
        station_id=station_id,
        name=f"Station {station_id}",
        city=city,
        state=state,
        latitude=35.0,
        longitude=-80.0,
        price=Decimal(price),
        distance_along_route_miles=position,
        distance_from_route_miles=0,
    )


class FuelStopOptimizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.optimizer = FuelStopOptimizer()

    def test_short_destination_uses_starting_full_tank(self) -> None:
        result = self.optimizer.optimize(route(300), [])

        self.assertEqual(result.number_of_stops, 0)
        self.assertEqual(result.total_gallons_purchased, Decimal("0"))
        self.assertEqual(result.total_cost, Decimal("0"))
        self.assertEqual(result.ending_fuel_gallons, Decimal("20"))

    def test_destination_exactly_500_miles_is_reachable_without_stop(self) -> None:
        result = self.optimizer.optimize(route(500), [])

        self.assertEqual(result.number_of_stops, 0)
        self.assertEqual(result.ending_fuel_gallons, Decimal("0"))

    def test_multiple_stops_and_total_fuel_accounting(self) -> None:
        result = self.optimizer.optimize(
            route(900),
            [station("a", 400, "4.00"), station("b", 800, "3.00")],
        )

        self.assertEqual([stop.station_id for stop in result.stops], ["a", "b"])
        self.assertEqual(result.total_gallons_consumed, Decimal("90"))
        self.assertEqual(result.total_gallons_purchased, Decimal("40"))
        self.assertEqual(result.total_cost, Decimal("150.00"))
        self.assertEqual(result.number_of_stops, 2)

    def test_no_station_in_reachable_gap_raises_domain_error(self) -> None:
        with self.assertRaises(FuelOptimizationError):
            self.optimizer.optimize(route(600), [station("too-late", 550, "3.00")])

    def test_expensive_but_necessary_station_is_used(self) -> None:
        result = self.optimizer.optimize(
            route(900),
            [station("necessary", 400, "5.00"), station("cheap", 800, "2.00")],
        )

        self.assertEqual([stop.station_id for stop in result.stops], ["necessary", "cheap"])
        self.assertEqual(result.total_cost, Decimal("170.00"))

    def test_cheaper_station_farther_ahead_changes_purchase_amount(self) -> None:
        result = self.optimizer.optimize(
            route(900),
            [
                station("near-expensive", 100, "4.00"),
                station("far-cheap", 450, "2.00"),
                station("later", 800, "3.00"),
            ],
        )

        self.assertEqual([stop.station_id for stop in result.stops], ["far-cheap"])
        self.assertEqual(result.stops[0].gallons_purchased, Decimal("40"))
        self.assertEqual(result.total_cost, Decimal("80.00"))

    def test_price_ties_are_deterministic_and_partial_refuelling_is_used(self) -> None:
        result = self.optimizer.optimize(
            route(1000),
            [station("first", 400, "3.00"), station("second", 800, "3.00")],
        )

        self.assertEqual([stop.station_id for stop in result.stops], ["first", "second"])
        self.assertEqual(result.stops[0].gallons_purchased, Decimal("40"))
        self.assertEqual(result.stops[1].gallons_purchased, Decimal("10"))

    def test_duplicate_station_records_are_collapsed(self) -> None:
        result = self.optimizer.optimize(
            route(900),
            [station("duplicate", 400, "4.00"), station("duplicate", 400, "3.00")],
        )

        self.assertEqual(len(result.stops), 1)
        self.assertEqual(result.stops[0].price_per_gallon, Decimal("3.00"))

    def test_custom_starting_fuel_is_accounted_for(self) -> None:
        optimizer = FuelStopOptimizer(FuelOptimizerConfig(starting_fuel_gallons=20))
        result = optimizer.optimize(route(300), [station("start-fuel", 100, "3.00")])

        self.assertEqual(result.total_gallons_consumed, Decimal("30"))
        self.assertEqual(result.total_gallons_purchased, Decimal("10"))
        self.assertEqual(result.stops[0].gallons_purchased, Decimal("10"))

    def test_only_station_at_destination_is_not_selected(self) -> None:
        result = self.optimizer.optimize(route(300), [station("destination", 300, "1.00")])

        self.assertEqual(result.number_of_stops, 0)

    def test_gallons_and_cost_use_decimal_precision(self) -> None:
        result = self.optimizer.optimize(
            route(900),
            [station("precise", 400, "3.12345678"), station("last", 800, "3.00000001")],
        )

        self.assertEqual(result.total_gallons_purchased, Decimal("40"))
        self.assertEqual(result.total_cost, Decimal("123.703703500"))

    def test_non_finite_vehicle_configuration_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            FuelOptimizerConfig(max_range_miles=inf)
