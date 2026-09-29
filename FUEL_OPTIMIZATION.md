# Fuel-stop optimization

## Scope

The optimizer minimizes fuel purchase cost along one already-selected route. It does not choose between alternate road routes and it does not make routing or geocoding API calls. Its inputs are the route distance and the ordered `MatchedStation` candidates produced by the route-corridor matcher.

Implementation: [`src/apps/routing/fuel.py`](src/apps/routing/fuel.py).

## Vehicle model

The default assessment constants are:

```text
MAX_RANGE_MILES = 500
MPG = 10
TANK_CAPACITY_GALLONS = MAX_RANGE_MILES / MPG = 50
```

The starting fuel amount is configurable through `FuelOptimizerConfig`. The default is a full 50-gallon tank. The destination requires no reserve fuel: arriving with zero gallons is valid. A route shorter than the available starting fuel is therefore completed without buying fuel.

The optimizer validates that MPG, maximum range, and tank capacity are positive, tank capacity equals maximum range divided by MPG, and starting fuel is between zero and tank capacity.

## Route graph

The input is converted into ordered route nodes:

```text
start(position=0, starting_fuel)
station_1(position=d1, price=p1)
...
station_n(position=dn, price=pn)
destination(position=D, no price)
```

Only stations with a valid price, a finite route position, and `0 <= position < D` are considered. Stations at or beyond the destination are not selected because no fuel is required after arrival. Duplicate records with the same station ID and route position are reduced to the cheapest deterministic record before optimization.

For a leg of `m` miles:

```text
fuel_required = m / MPG
```

A transition is feasible only when `fuel_required <= current_fuel`, and every purchase is bounded by the 50-gallon tank capacity. If the next required node cannot be reached with the current fuel, the optimizer raises `FuelOptimizationError` instead of inventing a stop or allowing negative fuel.

## Deterministic minimum-cost strategy

Fuel state is continuous, so a one-gallon or 0.1-gallon grid would introduce unnecessary approximation. The implementation uses the exact continuous-state forward policy for a route-ordered fuel graph:

1. Travel to each station in route order using the fuel currently available.
2. From the current station, find the first strictly cheaper station that is within the vehicle's full-tank range.
3. If a cheaper reachable station exists, purchase only enough fuel to reach it. Existing fuel is used first, so partial refuelling is naturally supported.
4. If no cheaper station is reachable within a full tank, purchase enough to fill the tank, except when the destination is closer; in that case purchase only enough to reach the destination.
5. Continue until the destination is reached.

This is not an “always choose the cheapest station” rule. A cheaper station is useful only if it can be reached. A more expensive station is selected when it is necessary to bridge a gap, and the optimizer may buy only the minimum gallons needed there.

### Why the policy is optimal on the selected route

At a station with price `p`, buying fuel that could instead be purchased at a reachable future station with price `< p` is strictly more expensive, so the optimal policy buys only enough to reach the first such cheaper station. If no cheaper station is reachable with a full tank, every feasible future purchase before the next range boundary costs at least `p`; filling the tank at `p` cannot increase future cost and preserves maximum reachability. Near the destination, the same argument is capped by the remaining distance because excess fuel has no value.

These two cases cover every station decision under the stated fixed-route, continuous-fuel assumptions. The route order and range constraint make the state graph acyclic, so the policy yields the minimum fuel purchase cost for that selected route. It does not optimize the road route itself or account for station access roads, traffic, or alternate routing choices. Price ties are resolved by treating the current price as not strictly cheaper and retaining deterministic route/station ordering.

## Accounting contract

For route distance `D`:

```text
total_gallons_consumed = D / MPG
total_gallons_purchased = starting_fuel + total_gallons_consumed - ending_fuel
total_cost = sum(gallons_purchased_at_stop * station_price)
```

The implementation uses `Decimal` for gallons, price, and cost calculations. Route distances remain floating-point geographic measurements and are converted to Decimal from their string representation at the fuel boundary. No intermediate currency rounding is performed; presentation/API serialization can round to cents later.

The result contains total distance, total gallons consumed, total gallons purchased, total cost, ending fuel, stop count, and for each stop: station ID/name, city/state, coordinates, price, route distance, gallons purchased, and cost.

## Failure cases

`FuelOptimizationError` is raised when the route distance is invalid, a station/node sequence is not ordered, starting fuel cannot reach the first required station, a station gap exceeds available fuel/range, or the destination cannot be reached after the final usable station.

No station is valid for routes up to 500 miles and infeasible for longer routes unless a usable station sequence exists.

## Complexity and determinism

With `n` route candidates, sorting and candidate preparation is `O(n log n)`. The next-cheaper station lookup uses a monotonic stack in `O(n)` time and `O(n)` memory; the final forward pass is also `O(n)`. The route-corridor matcher remains the dominant local geometry cost for large candidate sets.

Output is deterministic because candidates are sorted by route distance and station ID, duplicate records use the cheapest price then station ID, and price ties do not trigger arbitrary refuelling decisions.

## Tested scenarios

Independent unit tests cover short, exact-range, and long destinations; multiple stops; no reachable gap; necessary expensive stations; cheaper stations farther ahead; price ties; partial refuelling; duplicate records; configurable starting fuel; destination stations; long-precision costs; and floating-point-safe accounting.
