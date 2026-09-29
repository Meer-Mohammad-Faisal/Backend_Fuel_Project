from __future__ import annotations

import csv
import tempfile
from decimal import Decimal
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase

from apps.stations.geocoding import GeocodeResult, GeocodingService
from apps.stations.models import GeocodeCache, GeocodeStatus, Station
from apps.stations.services import station_identity_key

HEADERS = [
    "OPIS Truckstop ID",
    "Truckstop Name",
    "Address",
    "City",
    "State",
    "Rack ID",
    "Retail Price",
]


class StationImportTests(TestCase):
    def run_import(self, rows: list[list[str]], *args: str) -> str:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", newline="", delete=False) as file:
            writer = csv.writer(file)
            writer.writerow(HEADERS)
            writer.writerows(rows)
            path = Path(file.name)
        try:
            from io import StringIO

            output = StringIO()
            call_command("import_fuel_stations", path, *args, stdout=output)
            return output.getvalue()
        finally:
            path.unlink()

    def test_valid_import_normalizes_and_preserves_observations(self) -> None:
        output = self.run_import(
            [
                ["20", " Pilot #1243 ", "I-8, EXIT 119", "Gila Bend", "AZ", "930", "3.899"],
                [
                    "20",
                    "Pilot Travel Center #1243",
                    "I-8, EXIT 119",
                    "Gila Bend",
                    "AZ",
                    "930",
                    "3.799",
                ],
                ["21", "Other Stop", "US-1", "Miami", "FL", "931", "3.100"],
            ]
        )

        self.assertIn("imported_stations=2", output)
        self.assertEqual(Station.objects.count(), 2)
        self.assertEqual(
            Station.objects.get(source_opis_id="20").retail_price,
            Decimal("3.79900000"),
        )
        self.assertEqual(Station.objects.get(source_opis_id="20").aliases.count(), 2)
        self.assertEqual(Station.objects.get(source_opis_id="20").price_observations.count(), 2)

    def test_malformed_and_invalid_price_rows_are_reported_and_skipped(self) -> None:
        output = self.run_import(
            [
                ["20", "Valid", "US-1", "City", "TX", "930", "3.899"],
                ["21", "Bad Price", "US-2", "City", "TX", "931", "0"],
                ["22", "Short Row", "US-3"],
            ]
        )

        self.assertIn("malformed_rows=2", output)
        self.assertEqual(Station.objects.count(), 1)

    def test_reimport_is_idempotent(self) -> None:
        rows = [["20", "Valid", "US-1", "City", "TX", "930", "3.899"]]
        first = self.run_import(rows)
        second = self.run_import(rows)

        self.assertIn("imported_stations=1", first)
        self.assertIn("imported_stations=0", second)
        self.assertIn("updated_stations=0", second)
        self.assertIn("skipped_duplicate_rows=1", second)
        self.assertEqual(Station.objects.count(), 1)
        self.assertEqual(Station.objects.first().price_observations.count(), 1)

    def test_strict_import_rolls_back_malformed_file(self) -> None:
        rows = [["20", "Valid", "US-1", "City", "TX", "930", "3.899"], ["21", "Bad", "US-2"]]

        with self.assertRaises(CommandError):
            self.run_import(rows, "--strict")

        self.assertEqual(Station.objects.count(), 0)

    def test_missing_required_column_is_rejected(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", newline="", delete=False) as file:
            writer = csv.writer(file)
            writer.writerow([column for column in HEADERS if column != "Retail Price"])
            path = Path(file.name)
        try:
            with self.assertRaises(CommandError) as context:
                call_command("import_fuel_stations", path)
            self.assertIn("Retail Price", str(context.exception))
        finally:
            path.unlink()


class FakeGeocoder:
    provider_name = "fake"
    max_retries = 1

    def __init__(self) -> None:
        self.calls = 0

    def geocode(self, query: str) -> GeocodeResult:
        self.calls += 1
        return GeocodeResult(GeocodeStatus.SUCCESS, 35.0, -80.0, "Fake result")


class GeocodingCacheTests(TestCase):
    def test_geocode_result_is_persisted_and_reused(self) -> None:
        station = Station.objects.create(
            identity_key=station_identity_key("20", "US-1", "City", "TX"),
            source_opis_id="20",
            name="Valid",
            address="US-1",
            city="City",
            state="TX",
            rack_id="930",
            retail_price="3.899",
        )
        provider = FakeGeocoder()
        service = GeocodingService(provider)  # type: ignore[arg-type]

        first, first_cached = service.geocode_station(station)
        second, second_cached = service.geocode_station(station)

        self.assertEqual(first.status, GeocodeStatus.SUCCESS)
        self.assertFalse(first_cached)
        self.assertTrue(second_cached)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(GeocodeCache.objects.count(), 1)
        station.refresh_from_db()
        self.assertEqual(station.latitude, Decimal("35.000000"))
        self.assertEqual(station.longitude, Decimal("-80.000000"))

    def test_location_success_is_cached(self) -> None:
        provider = FakeGeocoder()
        service = GeocodingService(provider)  # type: ignore[arg-type]

        first, first_cached = service.geocode_location("Charlotte, NC")
        second, second_cached = service.geocode_location("  charlotte, nc ")

        self.assertEqual(first.status, GeocodeStatus.SUCCESS)
        self.assertFalse(first_cached)
        self.assertTrue(second_cached)
        self.assertEqual(provider.calls, 1)

    def test_provider_failure_is_cached_as_invalid_location(self) -> None:
        class FailingGeocoder(FakeGeocoder):
            def geocode(self, query: str) -> GeocodeResult:
                self.calls += 1
                return GeocodeResult(GeocodeStatus.FAILED, error="provider unavailable")

        provider = FailingGeocoder()
        service = GeocodingService(provider)  # type: ignore[arg-type]

        first, first_cached = service.geocode_location("Not a real US place")
        second, second_cached = service.geocode_location("Not a real US place")

        self.assertEqual(first.status, GeocodeStatus.FAILED)
        self.assertFalse(first_cached)
        self.assertTrue(second_cached)
        self.assertEqual(provider.calls, 1)
