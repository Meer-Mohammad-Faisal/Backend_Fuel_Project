from __future__ import annotations

from unittest.mock import Mock

from django.core.cache import cache
from django.test import SimpleTestCase

from apps.routing.domain import (
    Coordinate,
    MalformedRoutingResponse,
    RouteResult,
    RoutingProviderError,
)
from apps.routing.providers.osrm import OsrmRoutingProvider
from apps.routing.services import RouteService


def osrm_payload() -> dict:
    return {
        "code": "Ok",
        "routes": [
            {
                "distance": 12345.6,
                "duration": 987.5,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-80.0, 35.0], [-79.0, 36.0]],
                },
            }
        ],
    }


class OsrmRoutingProviderTests(SimpleTestCase):
    def setUp(self) -> None:
        self.session = Mock()
        self.response = Mock(status_code=200)
        self.response.json.return_value = osrm_payload()
        self.session.get.return_value = self.response
        self.provider = OsrmRoutingProvider(
            base_url="https://router.example.test",
            connect_timeout_seconds=2,
            read_timeout_seconds=5,
            session=self.session,
        )
        self.start = Coordinate(35.0, -80.0)
        self.destination = Coordinate(36.0, -79.0)

    def test_successful_response_returns_metrics_and_geojson(self) -> None:
        result = self.provider.route(self.start, self.destination, profile="driving")

        self.assertEqual(result.distance_meters, 12345.6)
        self.assertEqual(result.duration_seconds, 987.5)
        self.assertEqual(result.distance_miles, 12345.6 / 1609.344)
        self.assertEqual(result.geometry["type"], "LineString")
        self.session.get.assert_called_once()
        request = self.session.get.call_args
        self.assertEqual(request.kwargs["timeout"], (2, 5))
        self.assertEqual(request.kwargs["params"]["geometries"], "geojson")
        self.assertEqual(request.kwargs["params"]["overview"], "full")

    def test_non_200_response_is_safe_provider_error(self) -> None:
        self.response.status_code = 503

        with self.assertRaises(RoutingProviderError):
            self.provider.route(self.start, self.destination, profile="driving")

    def test_malformed_response_is_rejected(self) -> None:
        self.response.json.return_value = {"code": "Ok", "routes": []}

        with self.assertRaises(MalformedRoutingResponse):
            self.provider.route(self.start, self.destination, profile="driving")

    def test_invalid_json_is_rejected(self) -> None:
        self.response.json.side_effect = ValueError("invalid json")

        with self.assertRaises(MalformedRoutingResponse):
            self.provider.route(self.start, self.destination, profile="driving")

    def test_invalid_geometry_coordinate_is_rejected(self) -> None:
        payload = osrm_payload()
        payload["routes"][0]["geometry"]["coordinates"][1] = [float("nan"), 36.0]
        self.response.json.return_value = payload

        with self.assertRaises(MalformedRoutingResponse):
            self.provider.route(self.start, self.destination, profile="driving")

    def test_http_client_failure_is_wrapped(self) -> None:
        import requests

        self.session.get.side_effect = requests.Timeout("timed out")

        with self.assertRaises(RoutingProviderError):
            self.provider.route(self.start, self.destination, profile="driving")

    def test_provider_no_route_is_safe_provider_error(self) -> None:
        self.response.json.return_value = {"code": "NoRoute", "routes": []}

        with self.assertRaises(RoutingProviderError):
            self.provider.route(self.start, self.destination, profile="driving")


class RouteServiceTests(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()
        self.provider = Mock()
        self.provider.route.return_value = RouteResult(
            distance_meters=1000,
            duration_seconds=60,
            geometry={"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
            provider="fake",
            profile="driving",
        )
        self.service = RouteService(self.provider, cache_backend=cache, cache_ttl_seconds=60)
        self.start = Coordinate(35.0, -80.0)
        self.destination = Coordinate(36.0, -79.0)

    def tearDown(self) -> None:
        cache.clear()

    def test_cached_result_prevents_duplicate_provider_calls(self) -> None:
        first = self.service.calculate(self.start, self.destination)
        second = self.service.calculate(self.start, self.destination)

        self.assertEqual(first, second)
        self.provider.route.assert_called_once()

    def test_provider_error_is_propagated_as_typed_routing_error(self) -> None:
        self.provider.route.side_effect = RoutingProviderError("Routing provider returned an error")

        with self.assertRaises(RoutingProviderError):
            self.service.calculate(self.start, self.destination)
