# Testing

The automated suite is intentionally focused on deterministic business behavior. External geocoding and routing providers are mocked; no test requires internet access.

Run the complete suite:

```powershell
python manage.py test
```

Generate the branch coverage report:

```powershell
python -m coverage run --branch manage.py test
python -m coverage report -m
```

The suite covers:

- CSV schema validation, malformed rows, invalid prices, duplicate identities, strict rollback, and idempotent imports.
- Persisted geocoding successes and failures, cache hits, and provider-call suppression.
- OSRM success parsing, GeoJSON validation, malformed responses, non-200 responses, timeout wrapping, and route-cache hits.
- Route corridor projection, route boundaries, multi-segment geometry, long routes, distance filtering, and duplicate station reduction.
- Full-tank and custom-starting-fuel behavior, 500-mile boundaries, multiple stops, partial refueling, price-aware decisions, necessary expensive stations, infeasible routes, duplicate records, and Decimal precision.
- API validation, response shape, request IDs, location failures, routing failures, and infeasible fuel plans.

Coverage is used as a diagnostic for untested branches; business behavior and provider isolation are more important than maximizing a percentage.
