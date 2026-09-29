from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from threading import Lock
from typing import Any

from django.core.cache import cache

from apps.routing.domain import Coordinate, RouteResult
from apps.routing.providers.base import RoutingProvider


class RouteService:
    """Calculate and cache one normalized route result."""

    cache_namespace = "route:v1"

    def __init__(
        self,
        provider: RoutingProvider,
        *,
        cache_backend: Any = cache,
        cache_ttl_seconds: int = 86_400,
        default_profile: str = "driving",
    ) -> None:
        self.provider = provider
        self.cache_backend = cache_backend
        self.cache_ttl_seconds = cache_ttl_seconds
        self.default_profile = default_profile
        self._cache_lock = Lock()

    def calculate(
        self,
        start: Coordinate,
        destination: Coordinate,
        *,
        profile: str | None = None,
        options: Mapping[str, str] | None = None,
    ) -> RouteResult:
        effective_profile = profile or self.default_profile
        cache_key = self.cache_key(
            start,
            destination,
            profile=effective_profile,
            options=options,
        )
        cached = self.cache_backend.get(cache_key)
        if cached is not None:
            return RouteResult.from_cache_value(cached)

        # Re-check inside a process-level single-flight lock so simultaneous
        # requests do not duplicate a cold provider call in the normal worker.
        with self._cache_lock:
            cached = self.cache_backend.get(cache_key)
            if cached is not None:
                return RouteResult.from_cache_value(cached)
            result = self.provider.route(
                start,
                destination,
                profile=effective_profile,
                options=options,
            )
            self.cache_backend.set(cache_key, result.as_cache_value(), self.cache_ttl_seconds)
            return result

    @classmethod
    def cache_key(
        cls,
        start: Coordinate,
        destination: Coordinate,
        *,
        profile: str,
        options: Mapping[str, str] | None,
    ) -> str:
        payload = {
            "start": [start.latitude, start.longitude],
            "destination": [destination.latitude, destination.longitude],
            "profile": profile,
            "options": dict(sorted((options or {}).items())),
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return f"{cls.cache_namespace}:{digest}"


def configured_route_service() -> RouteService:
    from django.conf import settings

    from apps.routing.providers.osrm import OsrmRoutingProvider

    provider = OsrmRoutingProvider(
        base_url=settings.OSRM_BASE_URL,
        connect_timeout_seconds=settings.ROUTING_CONNECT_TIMEOUT_SECONDS,
        read_timeout_seconds=settings.ROUTING_READ_TIMEOUT_SECONDS,
    )
    return RouteService(
        provider,
        cache_ttl_seconds=settings.ROUTE_CACHE_TTL_SECONDS,
        default_profile=settings.OSRM_PROFILE,
    )
