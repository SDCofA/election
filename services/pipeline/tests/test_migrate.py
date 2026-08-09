from pathlib import Path

import pytest

from elexion_pipeline.migrate import discover_migrations


def test_migrations_are_ordered_and_content_addressed():
    root = Path(__file__).parents[3] / "infra" / "postgres"
    migrations = discover_migrations(root)
    assert [migration.version for migration in migrations] == [
        "001_schema",
        "002_calendar_revisions",
    ]
    assert all(len(migration.sha256) == 64 for migration in migrations)


def test_missing_baseline_fails_closed(tmp_path):
    (tmp_path / "migrations").mkdir()
    with pytest.raises(FileNotFoundError, match="001_schema"):
        discover_migrations(tmp_path)
