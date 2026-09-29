from __future__ import annotations

import uuid

from django.db import models


class GeocodeStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SUCCESS = "success", "Success"
    FAILED = "failed", "Failed"


class Station(models.Model):
    """Canonical station identity derived from one or more source rows."""

    station_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    identity_key = models.CharField(max_length=64, unique=True, db_index=True)
    source_opis_id = models.CharField(max_length=32, db_index=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=128)
    state = models.CharField(max_length=8)
    rack_id = models.CharField(max_length=32)
    retail_price = models.DecimalField(max_digits=10, decimal_places=8)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    geocode_status = models.CharField(
        max_length=16,
        choices=GeocodeStatus.choices,
        default=GeocodeStatus.PENDING,
    )
    geocode_provider = models.CharField(max_length=64, blank=True)
    geocode_query = models.CharField(max_length=512, blank=True)
    geocode_display_name = models.CharField(max_length=512, blank=True)
    geocode_error = models.TextField(blank=True)
    geocoded_at = models.DateTimeField(null=True, blank=True)
    imported_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["state", "city", "name", "station_id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(retail_price__gt=0),
                name="station_retail_price_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(latitude__isnull=True, longitude__isnull=True)
                    | models.Q(latitude__isnull=False, longitude__isnull=False)
                ),
                name="station_coordinates_together",
            ),
        ]
        indexes = [
            models.Index(
                fields=["geocode_status", "latitude", "longitude"],
                name="station_geo_candidate_idx",
            ),
        ]


class StationAlias(models.Model):
    """Source names observed for a canonical station."""

    station = models.ForeignKey(Station, on_delete=models.CASCADE, related_name="aliases")
    name = models.CharField(max_length=255)
    normalized_name = models.CharField(max_length=255)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["station", "normalized_name"],
                name="unique_station_alias_name",
            ),
        ]


class FuelPriceObservation(models.Model):
    """An auditable source-row price observation preserved across imports."""

    station = models.ForeignKey(
        Station,
        on_delete=models.CASCADE,
        related_name="price_observations",
    )
    source_row_hash = models.CharField(max_length=64, unique=True)
    source_file_name = models.CharField(max_length=255)
    source_row_number = models.PositiveIntegerField()
    source_opis_id = models.CharField(max_length=32)
    source_name = models.CharField(max_length=255)
    source_address = models.CharField(max_length=255)
    source_city = models.CharField(max_length=128)
    source_state = models.CharField(max_length=8)
    rack_id = models.CharField(max_length=32)
    retail_price = models.DecimalField(max_digits=10, decimal_places=8)
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["source_file_name", "source_row_number"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(retail_price__gt=0),
                name="observation_retail_price_positive",
            ),
        ]


class GeocodeCache(models.Model):
    """Persistent provider response cache, including failed lookups."""

    provider = models.CharField(max_length=64)
    query_hash = models.CharField(max_length=64)
    query = models.CharField(max_length=512)
    status = models.CharField(max_length=16, choices=GeocodeStatus.choices)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    display_name = models.CharField(max_length=512, blank=True)
    error = models.TextField(blank=True)
    attempts = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "query_hash"],
                name="unique_geocode_provider_query",
            ),
        ]
