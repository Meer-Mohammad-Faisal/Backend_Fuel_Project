"""Local development settings."""

import os

from .base import *  # noqa: F403

DEBUG = os.getenv("DJANGO_DEBUG", "true").strip().lower() in {"1", "true", "yes", "on"}
