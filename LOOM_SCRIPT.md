# Five-minute Loom presentation script

This script is written to sound like a walkthrough rather than a memorized speech. The timestamps are approximate.

## 0:00–0:30 — Introduction

“Hi, this is my Backend Django Engineer assessment submission.

The problem is to accept a start and destination in the United States, calculate a driving route, find useful fuel stations along that route, and choose fuel stops based primarily on price while respecting the vehicle’s range.

The application exposes a Django REST API. It uses the supplied fuel-price CSV as local station data, OSRM for one driving route and its geometry, and performs station matching and fuel planning locally. There is no frontend because the assessment is API-focused.”

## 0:30–1:15 — Repository and architecture

“At the top level, `README.md` contains the setup and API contract, `ARCHITECTURE.md` explains the design, and the `postman` directory contains the demonstration collection.

The application itself is under `src`. The `stations` app owns the normalized station models, CSV import command, persisted geocoding, and repository access. The `routing` app contains the API, provider adapter, route cache, corridor matcher, optimizer, and request-level planning service. The API view is deliberately thin; `RoutePlanningService` coordinates the workflow.

The flow is: validate the request, geocode the two locations, retrieve or calculate one route, load local station candidates, match them to the route corridor, optimize fuel purchases, and serialize the result.”

## 1:15–2:00 — Routing and external-call strategy

“For routing, the application uses an `OsrmRoutingProvider`. It sends one request to the OSRM route endpoint with the driving profile, full route overview, and GeoJSON geometry enabled. That single response supplies distance, duration, and the `LineString` used for station matching.

The route service creates a deterministic cache key from the start and destination coordinates, profile, and options. A warm cache avoids the OSRM call. There are no routing calls per fuel station.

The two requested locations can result in up to two geocoding calls on a cold cache. Those results are persisted in `GeocodeCache`. Fuel stations are not geocoded during an API request; station enrichment is an explicit management command with throttling, retries, timeouts, and cached results. So the normal uncached request is at most two location geocoding calls and one routing call, with all station work local.”

## 2:00–3:00 — Fuel optimization

“The vehicle model follows the assessment: a 500-mile maximum range, 10 miles per gallon, and therefore a 50-gallon equivalent tank. The default starting assumption is a full tank, and no reserve fuel is required after reaching the destination.

The route geometry matcher gives every candidate a cumulative distance along the route. The optimizer orders those stations and uses their imported retail prices. It consumes fuel between route nodes, never allows fuel to go negative, and never exceeds tank capacity.

It supports partial refueling. At a station, it looks for the first strictly cheaper reachable station ahead. If one exists within the 500-mile range, it buys only enough to reach that station, using fuel already in the tank first. If there is no cheaper reachable station, it buys enough to reach the farthest useful point within range, capped by the tank and the destination distance.

This handles multiple stops and also forces an expensive station when that station is necessary to bridge a gap. The final response reports total miles, gallons consumed, gallons purchased, every selected stop, and total cost. Prices and costs use Decimal arithmetic, with currency rounded only for API presentation.

The guarantee is for the selected OSRM route and the stated continuous-fuel model. It does not try to choose the globally cheapest road route among alternatives.”

## 3:00–4:15 — Postman demonstration

“I’ll switch to Postman now. The collection uses a `base_url` variable, so the requests are portable between local development and Docker.

First, I’ll run the health check to confirm the service is available.

For the short successful example, I’ll send Washington, DC to Philadelphia. The request body is just `start` and `destination`. The response includes the geocoded endpoints, route distance and duration, and the GeoJSON route geometry.

For the fuel-stop demonstration, I’ll run the New York to Los Angeles request from the collection. This is a route long enough to require multiple fuel stops. This demonstration assumes the CSV has been imported and enough stations along the route have been geocoded with the management command.

In the response, I’ll point out the route distance, the `LineString` geometry, and the `fuel` summary. Each item in `stops` includes the station name and location, price per gallon, distance along the route, gallons purchased, and cost. The `total_cost` is the sum of those individual purchases. Repeating the same request demonstrates the cached location and route behavior.

The collection also includes an invalid request that returns a structured 400 error. The infeasible-plan example is disabled by default because a 422 depends on the station data currently loaded; it can be enabled against a controlled empty or insufficient station dataset.”

## 4:15–4:45 — Tests

“The tests do not depend on live OSRM or Nominatim. External providers are mocked.

There are 50 tests covering CSV validation and idempotency, geocoding cache behavior, routing response parsing and route caching, route-corridor geometry, optimizer edge cases including 500-mile boundaries and multiple stops, API validation and error mapping, and settings behavior.

The last coverage run reports about 90 percent branch-aware coverage. Ruff, MyPy, Django checks, and migration consistency checks also pass.”

## 4:45–5:00 — Decisions and conclusion

“The main engineering decisions were to keep the view thin, persist coordinates and cache external lookups, make station matching local and indexed, and keep the optimizer deterministic and independently testable.

The main production improvements I would add at larger scale are shared Redis caching and locking, PostGIS or a spatial grid, background station geocoding, and metrics around provider latency and cache hit rate.

That’s the overview of the submission. Thanks for reviewing it.”

## Exact Loom screens/files

Keep these ready in this order:

1. `README.md` — overview, setup, API contract, and limitations.
2. `ARCHITECTURE.md` — Mermaid flow and component responsibilities.
3. Repository tree showing `src/apps/stations`, `src/apps/routing`, `tests`, and `postman`.
4. `src/apps/routing/planning.py` — end-to-end orchestration.
5. `src/apps/routing/providers/osrm.py` and `src/apps/routing/services.py` — one-call routing and cache.
6. `src/apps/routing/matching.py` — corridor and route-position matching.
7. `src/apps/routing/fuel.py` — range, price, partial-refueling, and cost logic.
8. Postman collection — health, short route, and New York-to-Los Angeles request/response.
9. `tests/` and `TESTING.md` — test strategy and commands.
10. `Dockerfile`, `docker-compose.yml`, and `docker-entrypoint.sh` — container startup and migrations.

Before recording, verify that Docker is running, the CSV has been imported, and enough stations have been geocoded for the long-route response to contain fuel stops.
