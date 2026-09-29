from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from apps.stations.models import FuelPriceObservation, Station, StationAlias
from apps.stations.services import normalize_text, source_row_hash, station_identity_key

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = (
    "OPIS Truckstop ID",
    "Truckstop Name",
    "Address",
    "City",
    "State",
    "Rack ID",
    "Retail Price",
)


@dataclass
class ImportSummary:
    rows_seen: int = 0
    malformed_rows: int = 0
    imported_stations: int = 0
    updated_stations: int = 0
    imported_observations: int = 0
    skipped_duplicate_rows: int = 0
    duplicate_identity_rows: int = 0


@dataclass(frozen=True)
class ParsedRow:
    values: dict[str, str]
    price: Decimal
    identity: str
    observation_hash: str


class Command(BaseCommand):
    help = "Import fuel station and price observations from the assessment CSV."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("csv_path", type=Path)
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Rollback and fail if any malformed rows are found.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        csv_path: Path = options["csv_path"]
        if not csv_path.is_file():
            raise CommandError(f"CSV file does not exist: {csv_path}")

        summary = ImportSummary()
        with csv_path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.reader(source)
            try:
                headers = next(reader)
            except StopIteration as exc:
                raise CommandError("CSV file is empty") from exc

            missing = [column for column in REQUIRED_COLUMNS if column not in headers]
            if missing:
                raise CommandError(f"Missing required columns: {', '.join(missing)}")

            column_indexes = {column: headers.index(column) for column in REQUIRED_COLUMNS}
            parsed_rows: list[tuple[int, ParsedRow]] = []
            with transaction.atomic():
                for row_number, values in enumerate(reader, start=2):
                    summary.rows_seen += 1
                    if len(values) != len(headers):
                        self._malformed(
                            summary,
                            row_number,
                            "wrong number of columns",
                        )
                        continue
                    row = {column: values[index] for column, index in column_indexes.items()}
                    try:
                        parsed_rows.append((row_number, self._parse_row(row)))
                    except ValueError as exc:
                        self._malformed(summary, row_number, str(exc))

                if options["strict"] and summary.malformed_rows:
                    raise CommandError(f"Import aborted: {summary.malformed_rows} malformed rows")

                last_rows = {
                    parsed.identity: index
                    for index, (_, parsed) in enumerate(parsed_rows)
                }
                for index, (row_number, parsed) in enumerate(parsed_rows):
                    self._import_row(
                        parsed,
                        csv_path.name,
                        row_number,
                        summary,
                        canonical=index == last_rows[parsed.identity],
                    )

        self.stdout.write(self.style.SUCCESS(self._summary_text(summary)))

    @staticmethod
    def _parse_row(row: dict[str, str]) -> ParsedRow:
        values = {key: value.strip() for key, value in row.items()}
        required_nonempty = [key for key, value in values.items() if not value]
        if required_nonempty:
            raise ValueError(f"blank required field(s): {', '.join(required_nonempty)}")
        try:
            price = Decimal(values["Retail Price"])
        except InvalidOperation as exc:
            raise ValueError("Retail Price is not numeric") from exc
        if price <= 0:
            raise ValueError("Retail Price must be positive")

        identity = station_identity_key(
            values["OPIS Truckstop ID"],
            values["Address"],
            values["City"],
            values["State"],
        )
        return ParsedRow(
            values=values,
            price=price,
            identity=identity,
            observation_hash=source_row_hash([values[column] for column in REQUIRED_COLUMNS]),
        )

    def _import_row(
        self,
        parsed: ParsedRow,
        source_file_name: str,
        row_number: int,
        summary: ImportSummary,
        canonical: bool,
    ) -> None:
        values = parsed.values
        price = parsed.price
        station, created = Station.objects.get_or_create(
            identity_key=parsed.identity,
            defaults={
                "source_opis_id": values["OPIS Truckstop ID"],
                "name": values["Truckstop Name"],
                "address": values["Address"],
                "city": values["City"],
                "state": values["State"],
                "rack_id": values["Rack ID"],
                "retail_price": price,
            },
        )
        fields = {
            "source_opis_id": values["OPIS Truckstop ID"],
            "name": values["Truckstop Name"],
            "address": values["Address"],
            "city": values["City"],
            "state": values["State"],
            "rack_id": values["Rack ID"],
            "retail_price": price,
        }
        if created:
            summary.imported_stations += 1
        elif canonical:
            summary.duplicate_identity_rows += 1
            if any(getattr(station, field) != value for field, value in fields.items()):
                # File order is the deterministic tie-breaker because the source has no timestamp.
                for field, value in fields.items():
                    setattr(station, field, value)
                station.save()
                summary.updated_stations += 1
        elif not created:
            summary.duplicate_identity_rows += 1

        StationAlias.objects.get_or_create(
            station=station,
            normalized_name=normalize_text(values["Truckstop Name"]),
            defaults={"name": values["Truckstop Name"]},
        )
        _, created_observation = FuelPriceObservation.objects.get_or_create(
            source_row_hash=parsed.observation_hash,
            defaults={
                "station": station,
                "source_file_name": source_file_name,
                "source_row_number": row_number,
                "source_opis_id": values["OPIS Truckstop ID"],
                "source_name": values["Truckstop Name"],
                "source_address": values["Address"],
                "source_city": values["City"],
                "source_state": values["State"],
                "rack_id": values["Rack ID"],
                "retail_price": price,
            },
        )
        if created_observation:
            summary.imported_observations += 1
        else:
            summary.skipped_duplicate_rows += 1

    def _malformed(
        self,
        summary: ImportSummary,
        row_number: int,
        reason: str,
    ) -> None:
        summary.malformed_rows += 1
        logger.warning(
            "Skipping malformed fuel row",
            extra={"row_number": row_number, "reason": reason},
        )
        self.stderr.write(self.style.WARNING(f"Row {row_number}: skipped ({reason})"))
    @staticmethod
    def _summary_text(summary: ImportSummary) -> str:
        return (
            "Import complete: "
            f"rows_seen={summary.rows_seen}, "
            f"malformed_rows={summary.malformed_rows}, "
            f"imported_stations={summary.imported_stations}, "
            f"updated_stations={summary.updated_stations}, "
            f"imported_observations={summary.imported_observations}, "
            f"duplicate_identity_rows={summary.duplicate_identity_rows}, "
            f"skipped_duplicate_rows={summary.skipped_duplicate_rows}"
        )
