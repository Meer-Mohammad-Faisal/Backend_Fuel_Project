# Postman collection

Import [`Spotter-Backend-Django-Assessment.postman_collection.json`](Spotter-Backend-Django-Assessment.postman_collection.json) into Postman.

Create or select a Postman environment containing:

| Variable | Example initial value |
|---|---|
| `base_url` | `http://127.0.0.1:8000` |

The collection uses `{{base_url}}` for every request, so the same collection can target a local server, Docker, or another environment without editing request URLs.

Recommended run order:

1. Start the application with `docker compose up --build` or `python manage.py runserver`.
2. Import the CSV and geocode a controlled batch if a route response with fuel stops is required.
3. Run `Health check`.
4. Run `Route under 500 miles - Washington DC to Philadelphia`.
5. Run `Route requiring multiple fuel stops - New York to Los Angeles`.
6. Run `Invalid request - missing destination`.

The successful New York-to-Los Angeles request validates HTTP 200, route distance, GeoJSON geometry, fuel data, numeric cost, the stops array, and all required fields on every selected stop.

The `Infeasible fuel plan - optional dataset-dependent check` request is intentionally disabled. It reliably returns 422 only when the route is longer than the vehicle range and the database has no usable geocoded station sequence. Enable it in Postman after preparing that controlled state; do not include it in an ordinary run against a populated station database, because the same route may then be feasible.

The collection never calls a provider directly. External geocoding and routing calls are made by the application and are subject to the application cache and timeout policies.
