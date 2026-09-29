from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from config.settings.base import BASE_DIR, _database_config


class DatabaseSettingsTests(SimpleTestCase):
    def test_relative_sqlite_url_resolves_inside_project(self) -> None:
        with patch.dict("os.environ", {"DATABASE_URL": "sqlite:///db.sqlite3"}):
            config = _database_config()

        self.assertEqual(config["NAME"], str(Path(BASE_DIR) / "db.sqlite3"))

    def test_postgres_credentials_are_url_decoded(self) -> None:
        with patch.dict(
            "os.environ",
            {"DATABASE_URL": "postgresql://user%40example:p%40ss%3Aword@db:5432/fuel"},
        ):
            config = _database_config()

        self.assertEqual(config["USER"], "user@example")
        self.assertEqual(config["PASSWORD"], "p@ss:word")
