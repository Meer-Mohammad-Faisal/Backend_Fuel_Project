"""Logging helpers used by Django's safe console configuration."""

from __future__ import annotations

import logging


class RequestIDFilter(logging.Filter):
    """Ensure structured log formatting never fails for non-API log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return True
