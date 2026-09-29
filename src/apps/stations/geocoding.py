from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from threading import RLock
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.db import IntegrityError, transaction

from apps.stations.models import GeocodeCache, GeocodeStatus, Station
from apps.stations.services import normalize_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeocodeResult:
    status: GeocodeStatus
    latitude: float | None = None
    longitude: float | None = None
    display_name: str = ""
    error: str = ""
    attempts: int = 0


class NominatimGeocoder:
    provider_name = "nominatim"

    def __init__(
        self,
        *,
        base_url: str,
        user_agent: str,
        timeout_seconds: float,
        min_interval_seconds: float,
        max_retries: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self.min_interval_seconds = min_interval_seconds
        self.max_retries = max_retries
        self._sleeper = sleeper
        self._last_request_at: float | None = None

    def geocode(self, query: str) -> GeocodeResult:
        params = urlencode({"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "us"})
        request = Request(
            f"{self.base_url}/search?{params}",
            headers={"User-Agent": self.user_agent, "Accept": "application/json"},
        )
        last_error = "unknown geocoding error"

        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = json.load(response)
                if not payload:
                    return GeocodeResult(
                        GeocodeStatus.FAILED,
                        error="no geocoding result",
                        attempts=attempt,
                    )
                result = payload[0]
                return GeocodeResult(
                    status=GeocodeStatus.SUCCESS,
                    latitude=float(result["lat"]),
                    longitude=float(result["lon"]),
                    display_name=str(result.get("display_name", "")),
                    attempts=attempt,
                )
            except (HTTPError, URLError, TimeoutError, KeyError, ValueError) as exc:
                last_error = str(exc)
                logger.warning(
                    "Geocoding request failed",
                    extra={
                        "provider": self.provider_name,
                        "attempt": attempt,
                        "error_type": type(exc).__name__,
                    },
                )
                if attempt < self.max_retries:
                    self._sleeper(2 ** (attempt - 1))

        return GeocodeResult(
            GeocodeStatus.FAILED,
            error=last_error,
            attempts=self.max_retries,
        )

    def _throttle(self) -> None:
        if self._last_request_at is not None:
            wait_seconds = self.min_interval_seconds - (time.monotonic() - self._last_request_at)
            if wait_seconds > 0:
                self._sleeper(wait_seconds)
        self._last_request_at = time.monotonic()


class GeocodingService:
    """Persistent cache boundary for station geocoding."""

    def __init__(self, provider: NominatimGeocoder) -> None:
        self.provider = provider
        self._cache_lock = RLock()

    @transaction.atomic
    def geocode_station(self, station: Station) -> tuple[GeocodeResult, bool]:
        query = self._query_for(station)
        query_hash = sha256(normalize_text(query).encode("utf-8")).hexdigest()
        with self._cache_lock:
            cache = self._get_cache(query_hash)
            if cache is not None:
                result = self._result_from_cache(cache)
                self._apply_result(station, query, result)
                return result, True

            result = self.provider.geocode(query)
            cache, created = self._create_cache(
                query_hash=query_hash,
                query=query,
                result=result,
            )
            if not created:
                result = self._result_from_cache(cache)
            self._apply_result(station, query, result)
            return result, not created

    @transaction.atomic
    def geocode_location(self, query: str) -> tuple[GeocodeResult, bool]:
        """Geocode a user location once and persist both success and failure."""
        normalized_query = normalize_text(query)
        query_hash = sha256(normalized_query.encode("utf-8")).hexdigest()
        with self._cache_lock:
            cache = self._get_cache(query_hash)
            if cache is not None:
                return self._result_from_cache(cache), True

            result = self.provider.geocode(query)
            cache, created = self._create_cache(
                query_hash=query_hash,
                query=query,
                result=result,
            )
            if not created:
                result = self._result_from_cache(cache)
            return result, not created

    def _get_cache(self, query_hash: str) -> GeocodeCache | None:
        return GeocodeCache.objects.filter(
            provider=self.provider.provider_name,
            query_hash=query_hash,
        ).first()

    def _create_cache(
        self,
        *,
        query_hash: str,
        query: str,
        result: GeocodeResult,
    ) -> tuple[GeocodeCache, bool]:
        try:
            with transaction.atomic():
                cache = GeocodeCache.objects.create(
                    provider=self.provider.provider_name,
                    query_hash=query_hash,
                    query=query,
                    status=result.status,
                    latitude=result.latitude,
                    longitude=result.longitude,
                    display_name=result.display_name,
                    error=result.error,
                    attempts=result.attempts or 1,
                )
            return cache, True
        except IntegrityError:
            existing = self._get_cache(query_hash)
            if existing is None:
                raise
            return existing, False

    @staticmethod
    def _result_from_cache(cache: GeocodeCache) -> GeocodeResult:
        return GeocodeResult(
            status=GeocodeStatus(cache.status),
            latitude=float(cache.latitude) if cache.latitude is not None else None,
            longitude=float(cache.longitude) if cache.longitude is not None else None,
            display_name=cache.display_name,
            error=cache.error,
        )

    def _apply_result(self, station: Station, query: str, result: GeocodeResult) -> None:
        station.geocode_status = result.status
        station.geocode_provider = self.provider.provider_name
        station.geocode_query = query
        station.geocode_display_name = result.display_name
        station.geocode_error = result.error
        station.latitude = result.latitude
        station.longitude = result.longitude
        station.geocoded_at = datetime.now(UTC) if result.status == GeocodeStatus.SUCCESS else None
        station.save(
            update_fields=[
                "geocode_status",
                "geocode_provider",
                "geocode_query",
                "geocode_display_name",
                "geocode_error",
                "latitude",
                "longitude",
                "geocoded_at",
            ]
        )

    @staticmethod
    def _query_for(station: Station) -> str:
        return f"{station.name}, {station.address}, {station.city}, {station.state}, USA"


def configured_nominatim_geocoder() -> NominatimGeocoder:
    return NominatimGeocoder(
        base_url=settings.NOMINATIM_BASE_URL,
        user_agent=settings.NOMINATIM_USER_AGENT,
        timeout_seconds=settings.GEOCODER_TIMEOUT_SECONDS,
        min_interval_seconds=settings.GEOCODER_MIN_INTERVAL_SECONDS,
    )
