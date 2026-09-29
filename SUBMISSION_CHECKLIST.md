# Submission Checklist

Final audit performed: 2026-09-29.

## Readiness checklist

- [x] Working Django application — Django system checks passed.
- [x] REST API — health and route endpoints verified.
- [x] Fuel station dataset integration — actual 8,151-row CSV imported successfully; re-import is idempotent.
- [x] Routing integration — OSRM adapter, timeout handling, response validation, and route cache tested.
- [x] Route geometry — live smoke test returned GeoJSON `LineString` geometry.
- [x] Fuel-stop optimization — 500-mile range, 10 MPG, partial refueling, multiple stops, and infeasible gaps tested.
- [x] Total fuel cost — Decimal fuel/price arithmetic and API serialization tested.
- [x] Multiple stops — optimizer tests and Postman long-route example included.
- [x] Fresh clone works — documented; requires Python or Docker and the supplied CSV for station data.
- [x] Environment documented — `.env.example` and README are complete.
- [ ] Docker works — Compose configuration passed, but image build/start could not be executed because Docker Desktop was unavailable in the audit environment.
- [x] Database migrations work — migrations applied locally and `makemigrations --check --dry-run` passed.
- [x] Fuel data import works — actual CSV import command completed successfully.
- [x] Health endpoint works — live local request returned HTTP 200 and `{"status":"ok"}`.
- [x] Main API works — live local Washington, DC → Philadelphia request returned HTTP 200.
- [x] Route geometry works — live response contained provider geometry.
- [x] Fuel stops work — pure optimizer tests and API response schema tests passed; live stop output requires geocoded station data.
- [x] Total cost works — optimizer and API tests passed.
- [x] Multiple stops work — optimizer scenario and long-route Postman request are included.
- [x] Tests pass — 50 tests passed.
- [x] Coverage generated — 90% branch-aware coverage.
- [x] Postman collection works — JSON parses and uses the portable `{{base_url}}` variable.
- [x] README complete — setup, API, architecture, optimization, Docker, testing, and limitations documented.
- [x] No secrets committed — no `.env`, API keys, or credentials were found in source; Git history is not available in this workspace.
- [ ] Git status clean — this workspace is not currently initialized as a Git repository.
- [x] Ready for GitHub after Git initialization and first commit.
- [x] Ready for Loom after Docker Desktop is running and station coordinates are prepared.

## Repository hygiene

The submission source excludes `.env`, virtual environments, bytecode, IDE folders, databases, coverage output, and caches through `.gitignore`/`.dockerignore`. The current workspace still contains local ignored artifacts from testing (`db.sqlite3`, `.coverage`, `coverage.xml`, `htmlcov`, `.mypy_cache`, and `.ruff_cache`); remove them before the first Git commit. The supplied assessment CSV is source input, not a generated artifact, and may be kept locally or supplied separately.

No personal machine paths, debugging prints, abandoned route implementations, or hardcoded route results were found in application code.

## Exact commands from scratch

### Docker

```powershell
git clone <repository-url>
Set-Location <repository-directory>
Copy-Item .env.example .env
docker compose up --build
```

Migrations run automatically during container startup. Verify:

```powershell
curl.exe http://127.0.0.1:8000/api/v1/health/
```

Import the supplied CSV from the host:

```powershell
docker compose run --rm -v "${PWD}:/input:ro" web python manage.py import_fuel_stations /input/fuel-prices-for-be-assessment.csv
```

Enrich a controlled station batch when permitted by the geocoder policy:

```powershell
docker compose run --rm web python manage.py geocode_stations --limit 10
```

### Local Python

```powershell
git clone <repository-url>
Set-Location <repository-directory>
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python manage.py migrate
python manage.py import_fuel_stations fuel-prices-for-be-assessment.csv
python manage.py runserver
```

## Exact test commands

```powershell
python manage.py check
python manage.py test
python -m coverage run --branch manage.py test
python -m coverage report -m
ruff check .
mypy
python manage.py makemigrations --check --dry-run
```

## Exact Postman demo request

Import `postman/Spotter-Backend-Django-Assessment.postman_collection.json`, create an environment with:

```text
base_url = http://127.0.0.1:8000
```

Then send:

```http
POST {{base_url}}/api/v1/routes/
Content-Type: application/json
```

```json
{
  "start": "Washington, DC",
  "destination": "Philadelphia, PA"
}
```

For the multiple-stop demonstration, run the collection request named `Route requiring multiple fuel stops - New York to Los Angeles` after importing and geocoding enough station data along that route.

## Loom files to show

1. `README.md` and `ARCHITECTURE.md`.
2. `src/apps/routing/planning.py` for orchestration.
3. `src/apps/routing/providers/osrm.py` and `src/apps/routing/services.py` for the one-call/cache design.
4. `src/apps/routing/matching.py` for corridor matching.
5. `src/apps/routing/fuel.py` and `FUEL_OPTIMIZATION.md` for range, price, and cost logic.
6. `src/apps/stations/management/commands/import_fuel_stations.py` and `models.py` for data integration.
7. `tests/` and `TESTING.md` for automated verification.
8. `Dockerfile`, `docker-compose.yml`, and `docker-entrypoint.sh` for deployment.
9. The Postman collection and a successful API response.

## Known limitations

- Docker build/start was not executable in this audit because Docker Desktop was not running.
- Station coordinates require explicit geocoding and provider-policy compliance.
- The development route cache is process-local; multi-worker production should use shared cache/locking.
- Corridor matching approximates station road access and does not route each station.
- The API intentionally has no authentication because it was outside the assessment scope.
