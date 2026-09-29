# Performance

The route endpoint is deliberately designed as a small orchestration layer around cached external lookups and local computation. A request does not parse the CSV, geocode fuel stations, or call a routing service per station.

## Optimizations

- Route results are cached by a deterministic hash of start coordinates, destination coordinates, routing profile, and options. The default TTL is 24 hours (`ROUTE_CACHE_TTL_SECONDS`).
- Start and destination geocoding is persisted in `GeocodeCache`, including successful and failed lookups. A warm request therefore makes no geocoder call.
- Station coordinates are persisted on `Station`; the route request only reads stations with successful geocoding.
- The repository applies a conservative latitude/longitude corridor bounding box in SQL before Shapely projection. The composite `geocode_status, latitude, longitude` index supports this candidate query. The precise 5-mile corridor check remains local and uses an STRtree over route segments.
- Station rows are streamed with `QuerySet.iterator()`. The CSV is used only by the management command, never per request.
- The optimizer precomputes each station's next strictly cheaper station with a monotonic stack. This removes the previous quadratic suffix scanning and makes the price decision O(n) after candidates are sorted.
- OSRM uses one request with full GeoJSON route geometry. Its `requests.Session` is reused by the process-level configured service, with separate connect/read timeouts.
- The configured route-planning service is cached once per process, so provider sessions and service objects are not rebuilt for each request.
- A process-level single-flight lock rechecks the route cache before a cold OSRM call, preventing simultaneous requests in the same worker from duplicating that call. A shared cache/lock is still recommended for multi-worker deployments.

## Representative benchmark

Run:

```powershell
python scripts/benchmark_pipeline.py
```

The benchmark uses 6,738 deterministic in-memory station records, a warm geocoder result, a fake routing provider, the real corridor matcher, and the real optimizer. It makes no network calls. The command reports total local planning time, provider-call counts, SQL-prefilter-equivalent station counts, and optimizer time. Results vary by machine; the important invariants are zero geocoder calls for cached locations, one route call on a route-cache miss, and substantially fewer station rows entering precise matching than the full dataset.

One local run produced approximately 157 ms total planning time, 0 geocoder calls, 1 routing call, 6,738 source rows reduced to 1,245 corridor rows, 1,245 matched stations, and 6.5 ms optimizer time on a cold in-process route cache. This is a local service benchmark, not a network latency SLA.

## Baseline and expected bottlenecks

The main avoidable baseline costs were scanning every station through Shapely, repeatedly searching all later stations in the optimizer, rebuilding HTTP clients, and allowing repeated external calls on identical requests. Those are now removed from the normal path.

The remaining costs are route-provider latency on a cold route cache, geocoding latency on a cold location cache, and the local projection of the stations surviving the SQL bounding box. The first request for a new pair of locations is therefore expected to be slower than subsequent identical requests.

The development configuration uses Django's in-process cache for a simple assessment deployment. Multiple production workers should use a shared Redis-compatible Django cache so route results are shared across workers. If the dataset grows substantially, a spatial database index (PostGIS) or a precomputed spatial grid can replace the conservative numeric bounding-box prefilter; the current approach keeps the design portable and understandable for the assessment.

## Measurements to record in production

The application logs request IDs and external failures. A production deployment can add timing middleware or metrics around geocoding, routing, candidate loading, matching, and optimization without changing domain code. Useful measurements are p50/p95 response time, cold versus warm cache latency, provider call count, candidate-row count, matched-station count, and optimizer duration.
