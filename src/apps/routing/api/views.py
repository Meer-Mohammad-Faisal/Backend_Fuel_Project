from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid4

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.routing.api.serializers import RoutePlanResponseSerializer, RouteRequestSerializer
from apps.routing.domain import RoutingError
from apps.routing.fuel import FuelOptimizationError
from apps.routing.planning import (
    LocationNotFoundError,
    RoutePlan,
    configured_route_planning_service,
)

logger = logging.getLogger(__name__)


class RoutePlanView(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request: Request) -> Response:
        request_id = str(uuid4())
        serializer = RouteRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return self._error(
                status_code=status.HTTP_400_BAD_REQUEST,
                code="INVALID_REQUEST",
                message="Invalid request.",
                details=serializer.errors,
                request_id=request_id,
            )

        try:
            plan = configured_route_planning_service().plan(
                start_query=serializer.validated_data["start"],
                destination_query=serializer.validated_data["destination"],
            )
            response_serializer = RoutePlanResponseSerializer(data=self._payload(plan))
            response_serializer.is_valid(raise_exception=True)
            response = Response(response_serializer.validated_data, status=status.HTTP_200_OK)
        except LocationNotFoundError:
            response = self._error(
                status_code=status.HTTP_404_NOT_FOUND,
                code="LOCATION_NOT_FOUND",
                message="Unable to geocode requested location.",
                request_id=request_id,
            )
        except FuelOptimizationError as exc:
            logger.info(
                "No feasible fuel plan",
                extra={"request_id": request_id, "error": str(exc)},
            )
            response = self._error(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                code="NO_FEASIBLE_FUEL_PLAN",
                message="No feasible fuel plan exists for this route.",
                request_id=request_id,
            )
        except RoutingError as exc:
            logger.warning(
                "Routing provider failure",
                extra={"request_id": request_id, "error": str(exc)},
            )
            response = self._error(
                status_code=status.HTTP_502_BAD_GATEWAY,
                code="ROUTING_PROVIDER_ERROR",
                message="The routing provider is currently unavailable.",
                request_id=request_id,
            )
        except Exception:
            logger.exception("Unhandled route planning error", extra={"request_id": request_id})
            response = self._error(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                code="INTERNAL_ERROR",
                message="Unable to calculate the requested route.",
                request_id=request_id,
            )

        response["X-Request-ID"] = request_id
        return response

    @staticmethod
    def _payload(plan: RoutePlan) -> dict:
        fuel = plan.fuel
        return {
            "route": {
                "start": {
                    "query": plan.start.query,
                    "display_name": plan.start.display_name,
                    "latitude": plan.start.latitude,
                    "longitude": plan.start.longitude,
                },
                "destination": {
                    "query": plan.destination.query,
                    "display_name": plan.destination.display_name,
                    "latitude": plan.destination.latitude,
                    "longitude": plan.destination.longitude,
                },
                "distance_miles": plan.route.distance_miles,
                "duration_minutes": plan.route.duration_seconds / 60,
                "geometry": plan.route.geometry,
            },
            "vehicle": {
                "max_range_miles": 500,
                "mpg": 10,
                "tank_capacity_gallons": 50,
                "starting_fuel_gallons": 50,
            },
            "fuel": {
                "total_gallons": float(fuel.total_gallons_consumed),
                "total_gallons_purchased": float(fuel.total_gallons_purchased),
                "total_cost": float(
                    fuel.total_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                ),
                "stops_count": fuel.number_of_stops,
                "ending_fuel_gallons": float(fuel.ending_fuel_gallons),
            },
            "stops": [
                {
                    "station_id": stop.station_id,
                    "station_name": stop.station_name,
                    "city": stop.city,
                    "state": stop.state,
                    "latitude": stop.latitude,
                    "longitude": stop.longitude,
                    "price_per_gallon": float(stop.price_per_gallon),
                    "distance_along_route_miles": stop.distance_along_route_miles,
                    "gallons_purchased": float(stop.gallons_purchased),
                    "cost": float(stop.cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                }
                for stop in fuel.stops
            ],
        }

    @staticmethod
    def _error(
        *,
        status_code: int,
        code: str,
        message: str,
        request_id: str,
        details: dict | None = None,
    ) -> Response:
        return Response(
            {
                "error": {
                    "code": code,
                    "message": message,
                    "details": details or {},
                    "request_id": request_id,
                }
            },
            status=status_code,
        )
