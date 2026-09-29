from __future__ import annotations

from decimal import Decimal
from unittest.mock import Mock, patch

from rest_framework import status
from rest_framework.test import APITestCase

from apps.routing.domain import RouteResult, RoutingProviderError
from apps.routing.fuel import FuelOptimizationError, FuelOptimizationResult, SelectedFuelStop
from apps.routing.planning import (
    GeocodedLocation,
    LocationNotFoundError,
    RoutePlan,
    RoutePlanningService,
)
from apps.stations.geocoding import GeocodeResult, GeocodeStatus


def sample_plan() -> RoutePlan:
    return RoutePlan(
        start=GeocodedLocation("New York, NY", 40.7128, -74.006, "New York, New York, USA"),
        destination=GeocodedLocation(
            "Chicago, IL",
            41.8781,
            -87.6298,
            "Chicago, Illinois, USA",
        ),
        route=RouteResult(
            distance_meters=1_000_000,
            duration_seconds=36_000,
            geometry={"type": "LineString", "coordinates": [[-74.006, 40.7128], [-87.63, 41.8781]]},
            provider="fake",
            profile="driving",
        ),
        fuel=FuelOptimizationResult(
            total_distance_miles=621.371,
            total_gallons_consumed=Decimal("62.1371"),
            total_gallons_purchased=Decimal("12.1371"),
            total_cost=Decimal("42.4812"),
            number_of_stops=1,
            ending_fuel_gallons=Decimal("0"),
            stops=(
                SelectedFuelStop(
                    station_id="station-1",
                    station_name="Test Travel Center",
                    city="Gary",
                    state="IN",
                    latitude=41.6,
                    longitude=-87.3,
                    price_per_gallon=Decimal("3.499"),
                    distance_along_route_miles=500,
                    gallons_purchased=Decimal("12.1371"),
                    cost=Decimal("42.4812"),
                ),
            ),
        ),
    )


class RouteApiTests(APITestCase):
    @patch("apps.routing.api.views.configured_route_planning_service")
    def test_successful_request_returns_route_fuel_and_request_id(self, factory: Mock) -> None:
        service = Mock()
        service.plan.return_value = sample_plan()
        factory.return_value = service

        response = self.client.post(
            "/api/v1/routes/",
            {"start": "New York, NY", "destination": "Chicago, IL"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["route"]["distance_miles"], 621.371192237334)
        self.assertEqual(response.data["fuel"]["stops_count"], 1)
        self.assertEqual(response.data["stops"][0]["station_id"], "station-1")
        self.assertTrue(response["X-Request-ID"])
        self.assertEqual(set(response.data), {"route", "vehicle", "fuel", "stops"})
        self.assertEqual(
            set(response.data["route"]),
            {"start", "destination", "distance_miles", "duration_minutes", "geometry"},
        )
        service.plan.assert_called_once_with(
            start_query="New York, NY",
            destination_query="Chicago, IL",
        )

    @patch("apps.routing.api.views.configured_route_planning_service")
    def test_invalid_request_returns_400_without_calling_providers(self, factory: Mock) -> None:
        response = self.client.post("/api/v1/routes/", {"start": "x"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "INVALID_REQUEST")
        factory.assert_not_called()

    @patch("apps.routing.api.views.configured_route_planning_service")
    def test_missing_destination_returns_400_without_calling_providers(self, factory: Mock) -> None:
        response = self.client.post("/api/v1/routes/", {"start": "New York, NY"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "INVALID_REQUEST")
        factory.assert_not_called()

    @patch("apps.routing.api.views.configured_route_planning_service")
    def test_non_object_payload_returns_400(self, factory: Mock) -> None:
        response = self.client.post("/api/v1/routes/", ["New York, NY"], format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "INVALID_REQUEST")
        factory.assert_not_called()

    @patch("apps.routing.api.views.configured_route_planning_service")
    def test_geocoding_failure_returns_404(self, factory: Mock) -> None:
        service = Mock()
        service.plan.side_effect = LocationNotFoundError("not found")
        factory.return_value = service

        response = self.client.post(
            "/api/v1/routes/",
            {"start": "Unknown", "destination": "Chicago, IL"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"]["code"], "LOCATION_NOT_FOUND")
        self.assertNotIn("not found", str(response.data))

    @patch("apps.routing.api.views.configured_route_planning_service")
    def test_no_fuel_plan_returns_422(self, factory: Mock) -> None:
        service = Mock()
        service.plan.side_effect = FuelOptimizationError("internal detail")
        factory.return_value = service

        response = self.client.post(
            "/api/v1/routes/",
            {"start": "New York, NY", "destination": "Chicago, IL"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(response.data["error"]["code"], "NO_FEASIBLE_FUEL_PLAN")
        self.assertNotIn("internal detail", str(response.data))

    @patch("apps.routing.api.views.configured_route_planning_service")
    def test_routing_failure_returns_502(self, factory: Mock) -> None:
        service = Mock()
        service.plan.side_effect = RoutingProviderError("secret provider detail")
        factory.return_value = service

        response = self.client.post(
            "/api/v1/routes/",
            {"start": "New York, NY", "destination": "Chicago, IL"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(response.data["error"]["code"], "ROUTING_PROVIDER_ERROR")
        self.assertNotIn("secret provider detail", str(response.data))


class RoutePlanningServiceTests(APITestCase):
    def test_pipeline_geocodes_two_locations_and_routes_once(self) -> None:
        geocoder = Mock()
        geocoder.geocode_location.side_effect = [
            (GeocodeResult(GeocodeStatus.SUCCESS, 40.7, -74.0, "New York"), False),
            (GeocodeResult(GeocodeStatus.SUCCESS, 41.8, -87.6, "Chicago"), False),
        ]
        route_service = Mock()
        route_service.calculate.return_value = sample_plan().route
        repository = Mock()
        repository.candidates.return_value = []
        matcher = Mock()
        matcher.match.return_value = []
        optimizer = Mock()
        optimizer.optimize.return_value = sample_plan().fuel
        service = RoutePlanningService(
            geocoder=geocoder,
            route_service=route_service,
            station_repository=repository,
            matcher=matcher,
            optimizer=optimizer,
        )

        plan = service.plan("New York, NY", "Chicago, IL")

        self.assertEqual(plan.start.latitude, 40.7)
        geocoder.geocode_location.assert_any_call("New York, NY")
        geocoder.geocode_location.assert_any_call("Chicago, IL")
        route_service.calculate.assert_called_once()
        matcher.match.assert_called_once()
        optimizer.optimize.assert_called_once()

    def test_invalid_geocoder_coordinates_are_not_accepted(self) -> None:
        geocoder = Mock()
        geocoder.geocode_location.return_value = (
            GeocodeResult(GeocodeStatus.SUCCESS, 91.0, -74.0, "Invalid"),
            False,
        )
        service = RoutePlanningService(
            geocoder=geocoder,
            route_service=Mock(),
            station_repository=Mock(),
            matcher=Mock(),
            optimizer=Mock(),
        )

        with self.assertRaises(LocationNotFoundError):
            service.plan("Invalid", "Chicago, IL")
