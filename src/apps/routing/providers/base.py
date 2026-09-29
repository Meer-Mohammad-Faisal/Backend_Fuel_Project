from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from apps.routing.domain import Coordinate, RouteResult


class RoutingProvider(Protocol):
    def route(
        self,
        start: Coordinate,
        destination: Coordinate,
        *,
        profile: str,
        options: Mapping[str, str] | None = None,
    ) -> RouteResult: ...
