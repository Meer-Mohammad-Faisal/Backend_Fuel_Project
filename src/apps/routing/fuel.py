from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import isfinite

from apps.routing.domain import RouteResult
from apps.routing.matching import MatchedStation

MAX_RANGE_MILES = 500.0
MPG = 10.0
TANK_CAPACITY_GALLONS = MAX_RANGE_MILES / MPG
_EPSILON_MILES = 1e-7
_EPSILON_GALLONS = Decimal("0.00000001")


class FuelOptimizationError(Exception):
    """Raised when the destination cannot be reached with the available stations."""


@dataclass(frozen=True)
class FuelOptimizerConfig:
    max_range_miles: float = MAX_RANGE_MILES
    mpg: float = MPG
    tank_capacity_gallons: float | None = None
    starting_fuel_gallons: float | None = None

    def __post_init__(self) -> None:
        capacity = self.tank_capacity_gallons
        if capacity is None:
            capacity = self.max_range_miles / self.mpg
            object.__setattr__(self, "tank_capacity_gallons", capacity)
        starting_fuel = self.starting_fuel_gallons
        if starting_fuel is None:
            starting_fuel = capacity
            object.__setattr__(self, "starting_fuel_gallons", starting_fuel)
        if (
            not isfinite(self.max_range_miles)
            or not isfinite(self.mpg)
            or not isfinite(capacity)
            or self.max_range_miles <= 0
            or self.mpg <= 0
            or capacity <= 0
        ):
            raise ValueError("range, MPG, and tank capacity must be positive")
        if starting_fuel < 0 or starting_fuel > capacity:
            raise ValueError("starting fuel must be between zero and tank capacity")
        if abs(capacity * self.mpg - self.max_range_miles) > 1e-6:
            raise ValueError("tank capacity must equal maximum range divided by MPG")


@dataclass(frozen=True)
class SelectedFuelStop:
    station_id: str
    station_name: str
    city: str
    state: str
    latitude: float
    longitude: float
    price_per_gallon: Decimal
    distance_along_route_miles: float
    gallons_purchased: Decimal
    cost: Decimal


@dataclass(frozen=True)
class FuelOptimizationResult:
    total_distance_miles: float
    total_gallons_consumed: Decimal
    total_gallons_purchased: Decimal
    total_cost: Decimal
    number_of_stops: int
    ending_fuel_gallons: Decimal
    stops: tuple[SelectedFuelStop, ...]


class FuelStopOptimizer:
    """Deterministic price-aware forward fuel strategy for one fixed route."""

    def __init__(self, config: FuelOptimizerConfig | None = None) -> None:
        self.config = config or FuelOptimizerConfig()

    def optimize(
        self,
        route: RouteResult,
        stations: list[MatchedStation] | tuple[MatchedStation, ...],
    ) -> FuelOptimizationResult:
        total_distance = route.distance_miles
        if not isfinite(total_distance) or total_distance < 0:
            raise FuelOptimizationError("Route distance is invalid")

        candidates = self._prepare_candidates(stations, total_distance)
        fuel = Decimal(str(self.config.starting_fuel_gallons))
        capacity = Decimal(str(self.config.tank_capacity_gallons))
        mpg = Decimal(str(self.config.mpg))
        current_position = 0.0
        total_cost = Decimal("0")
        total_purchased = Decimal("0")
        selected_stops: list[SelectedFuelStop] = []
        next_lower_indexes = self._next_lower_indexes(candidates)

        for index, station in enumerate(candidates):
            leg_miles = station.distance_along_route_miles - current_position
            fuel = self._consume_for_leg(fuel, leg_miles, mpg)
            current_position = station.distance_along_route_miles

            cheaper_index = next_lower_indexes[index]
            cheaper_station = (
                candidates[cheaper_index]
                if cheaper_index is not None
                and candidates[cheaper_index].distance_along_route_miles
                - current_position
                <= self.config.max_range_miles + _EPSILON_MILES
                else None
            )
            target_miles = (
                cheaper_station.distance_along_route_miles - current_position
                if cheaper_station is not None
                else min(self.config.max_range_miles, total_distance - current_position)
            )
            desired_fuel = min(capacity, Decimal(str(target_miles)) / mpg)
            purchase = max(Decimal("0"), desired_fuel - fuel)
            if purchase > _EPSILON_GALLONS:
                cost = purchase * Decimal(str(station.price))
                fuel += purchase
                total_purchased += purchase
                total_cost += cost
                selected_stops.append(
                    SelectedFuelStop(
                        station_id=station.station_id,
                        station_name=station.name,
                        city=station.city,
                        state=station.state,
                        latitude=station.latitude,
                        longitude=station.longitude,
                        price_per_gallon=Decimal(str(station.price)),
                        distance_along_route_miles=station.distance_along_route_miles,
                        gallons_purchased=purchase,
                        cost=cost,
                    )
                )

        fuel = self._consume_for_leg(fuel, total_distance - current_position, mpg)
        consumed = Decimal(str(total_distance)) / mpg
        return FuelOptimizationResult(
            total_distance_miles=total_distance,
            total_gallons_consumed=consumed,
            total_gallons_purchased=total_purchased,
            total_cost=total_cost,
            number_of_stops=len(selected_stops),
            ending_fuel_gallons=fuel,
            stops=tuple(selected_stops),
        )

    @staticmethod
    def _next_lower_indexes(candidates: list[MatchedStation]) -> list[int | None]:
        """Find each station's first strictly cheaper station in O(n) time."""
        result: list[int | None] = [None] * len(candidates)
        stack: list[int] = []
        for index in range(len(candidates) - 1, -1, -1):
            price = Decimal(str(candidates[index].price))
            while stack and Decimal(str(candidates[stack[-1]].price)) >= price:
                stack.pop()
            result[index] = stack[-1] if stack else None
            stack.append(index)
        return result

    def _prepare_candidates(
        self,
        stations: list[MatchedStation] | tuple[MatchedStation, ...],
        total_distance: float,
    ) -> list[MatchedStation]:
        valid = [
            station
            for station in stations
            if 0 <= station.distance_along_route_miles < total_distance - _EPSILON_MILES
            and isfinite(station.distance_along_route_miles)
            and isfinite(station.price)
            and station.price > 0
        ]
        valid.sort(key=lambda station: (station.distance_along_route_miles, station.station_id))

        deduplicated: list[MatchedStation] = []
        seen: dict[tuple[str, float], MatchedStation] = {}
        for station in valid:
            key = (station.station_id, round(station.distance_along_route_miles, 6))
            previous = seen.get(key)
            if previous is None or (Decimal(str(station.price)), station.station_id) < (
                Decimal(str(previous.price)),
                previous.station_id,
            ):
                seen[key] = station
        deduplicated.extend(
            sorted(
                seen.values(),
                key=lambda item: (item.distance_along_route_miles, item.station_id),
            )
        )
        return deduplicated

    def _consume_for_leg(self, fuel: Decimal, miles: float, mpg: Decimal) -> Decimal:
        if miles < -_EPSILON_MILES:
            raise FuelOptimizationError("Route nodes are not ordered")
        required = Decimal(str(max(0.0, miles))) / mpg
        if required > fuel + _EPSILON_GALLONS:
            raise FuelOptimizationError(
                "Destination cannot be reached: no station is reachable in the required gap"
            )
        return max(Decimal("0"), fuel - required)
