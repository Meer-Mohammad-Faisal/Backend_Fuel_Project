from __future__ import annotations

import logging
from collections.abc import Mapping
from math import isfinite
from typing import Any, TypeGuard

import requests

from apps.routing.domain import (
    Coordinate,
    MalformedRoutingResponse,
    RouteResult,
    RoutingProviderError,
)

logger = logging.getLogger(__name__)


class OsrmRoutingProvider:
    """OSRM HTTP adapter; provider errors never escape as raw requests exceptions."""

    provider_name = "osrm"

    def __init__(
        self,
        *,
        base_url: str,
        connect_timeout_seconds: float,
        read_timeout_seconds: float,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.connect_timeout_seconds = connect_timeout_seconds
        self.read_timeout_seconds = read_timeout_seconds
        self.session = session or requests.Session()

    def route(
        self,
        start: Coordinate,
        destination: Coordinate,
        *,
        profile: str,
        options: Mapping[str, str] | None = None,
    ) -> RouteResult:
        request_options = {
            "alternatives": "false",
            "steps": "false",
            "overview": "full",
            "geometries": "geojson",
        }
        request_options.update(options or {})
        url = (
            f"{self.base_url}/route/v1/{profile}/"
            f"{start.longitude},{start.latitude};{destination.longitude},{destination.latitude}"
        )

        try:
            response = self.session.get(
                url,
                params=request_options,
                timeout=(self.connect_timeout_seconds, self.read_timeout_seconds),
                headers={"Accept": "application/json"},
            )
        except requests.RequestException as exc:
            logger.warning(
                "OSRM request failed",
                extra={"profile": profile, "error_type": type(exc).__name__},
            )
            raise RoutingProviderError("Routing provider request failed") from exc

        if response.status_code != 200:
            logger.warning(
                "OSRM returned a non-success status",
                extra={"profile": profile, "status_code": response.status_code},
            )
            raise RoutingProviderError("Routing provider returned an error")

        try:
            payload = response.json()
        except (ValueError, requests.exceptions.JSONDecodeError) as exc:
            raise MalformedRoutingResponse("Routing provider returned invalid JSON") from exc

        return self._parse_response(payload, profile)

    def _parse_response(self, payload: Any, profile: str) -> RouteResult:
        if not isinstance(payload, dict) or payload.get("code") != "Ok":
            raise RoutingProviderError("Routing provider did not return a route")
        routes = payload.get("routes")
        if not isinstance(routes, list) or not routes:
            raise MalformedRoutingResponse("Routing provider response has no routes")
        route = routes[0]
        if not isinstance(route, dict):
            raise MalformedRoutingResponse("Routing provider route is malformed")

        distance = route.get("distance")
        duration = route.get("duration")
        geometry = route.get("geometry")
        if not self._is_nonnegative_number(distance) or not self._is_nonnegative_number(duration):
            raise MalformedRoutingResponse("Routing provider route metrics are malformed")
        if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
            raise MalformedRoutingResponse("Routing provider geometry is not a LineString")
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            raise MalformedRoutingResponse("Routing provider geometry has insufficient coordinates")
        if any(
            not isinstance(point, list)
            or len(point) < 2
                or not self._valid_coordinate(point)
            for point in coordinates
        ):
            raise MalformedRoutingResponse("Routing provider geometry coordinates are malformed")

        return RouteResult(
            distance_meters=float(distance),
            duration_seconds=float(duration),
            geometry=geometry,
            provider=self.provider_name,
            profile=profile,
        )

    @staticmethod
    def _is_number(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    @classmethod
    def _valid_coordinate(cls, point: list[Any]) -> bool:
        longitude, latitude = point[:2]
        return (
            cls._is_number(longitude)
            and cls._is_number(latitude)
            and isfinite(float(longitude))
            and isfinite(float(latitude))
            and -180 <= longitude <= 180
            and -90 <= latitude <= 90
        )

    @classmethod
    def _is_nonnegative_number(cls, value: Any) -> TypeGuard[int | float]:
        return cls._is_number(value) and value >= 0
