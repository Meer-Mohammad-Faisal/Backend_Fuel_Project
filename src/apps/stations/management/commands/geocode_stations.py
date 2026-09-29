from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from apps.stations.geocoding import GeocodingService, configured_nominatim_geocoder
from apps.stations.models import GeocodeStatus, Station


class Command(BaseCommand):
    help = "Geocode pending fuel stations once, using the persistent provider cache."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--retry-failed", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        statuses = [GeocodeStatus.PENDING]
        if options["retry_failed"]:
            statuses.append(GeocodeStatus.FAILED)
        stations = Station.objects.filter(geocode_status__in=statuses).order_by("station_id")
        if options["limit"] > 0:
            stations = stations[: options["limit"]]

        service = GeocodingService(configured_nominatim_geocoder())
        success = failed = cache_hits = 0
        for station in stations:
            result, from_cache = service.geocode_station(station)
            cache_hits += int(from_cache)
            if result.status == GeocodeStatus.SUCCESS:
                success += 1
            else:
                failed += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Geocoding complete: success={success}, failed={failed}, cache_hits={cache_hits}"
            )
        )
