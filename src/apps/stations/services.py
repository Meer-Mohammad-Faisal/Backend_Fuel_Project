from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def station_identity_key(source_opis_id: str, address: str, city: str, state: str) -> str:
    """Return a stable identity for source ID plus normalized physical location."""
    identity = "|".join(
        normalize_text(value) for value in (source_opis_id, address, city, state)
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def source_row_hash(values: Iterable[str]) -> str:
    payload = "|".join(values)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
