from __future__ import annotations

from collections.abc import Iterable

from apps.routing.matching import StationRecord
from apps.stations.models import GeocodeStatus, Station


class StationRepository:
    """Read-only route candidate access; geocoding is never performed here."""

    def candidates(
        self,
        bounds: tuple[float, float, float, float] | None = None,
    ) -> Iterable[StationRecord]:
        queryset = Station.objects.filter(
            geocode_status=GeocodeStatus.SUCCESS,
            latitude__isnull=False,
            longitude__isnull=False,
            retail_price__gt=0,
        )
        if bounds is not None:
            min_latitude, max_latitude, min_longitude, max_longitude = bounds
            queryset = queryset.filter(
                latitude__gte=min_latitude,
                latitude__lte=max_latitude,
                longitude__gte=min_longitude,
                longitude__lte=max_longitude,
            )
        stations = queryset.only(
            "station_id",
            "name",
            "city",
            "state",
            "latitude",
            "longitude",
            "retail_price",
            "source_opis_id",
        )
        return (StationRecord.from_model(station) for station in stations.iterator())
