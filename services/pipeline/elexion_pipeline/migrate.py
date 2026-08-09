from __future__ import annotations

import argparse
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import psycopg

CORE_TABLES = (
    "jurisdictions",
    "sources",
    "source_revisions",
    "elections",
    "polls",
    "observations",
    "model_versions",
    "forecast_snapshots",
    "official_results",
    "audit_log",
)


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path
    sha256: str


def discover_migrations(root: Path) -> list[Migration]:
    paths = [root / "001_schema.sql", *sorted((root / "migrations").glob("*.sql"))]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing migration files: {missing}")
    migrations = [
        Migration(path.stem, path, hashlib.sha256(path.read_bytes()).hexdigest()) for path in paths
    ]
    versions = [migration.version for migration in migrations]
    if versions != sorted(versions) or len(versions) != len(set(versions)):
        raise ValueError("Migration versions must be unique and lexically ordered")
    return migrations


def migrate(dsn: str, root: Path) -> list[str]:
    migrations = discover_migrations(root)
    applied_now: list[str] = []
    with (
        psycopg.connect(dsn) as connection,
        connection.transaction(),
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext('elexion-schema-migrations'))")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
              version text PRIMARY KEY,
              sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
              applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        cursor.execute("SELECT version, sha256 FROM schema_migrations")
        applied = dict(cursor.fetchall())

        cursor.execute(
            "SELECT " + ", ".join("to_regclass(%s) IS NOT NULL" for _ in CORE_TABLES),
            tuple(f"public.{table}" for table in CORE_TABLES),
        )
        core_state = tuple(cursor.fetchone())
        if any(core_state) and not all(core_state):
            raise RuntimeError("Refusing to bless a partial unmanaged database schema")

        for position, migration in enumerate(migrations):
            previous = applied.get(migration.version)
            if previous is not None:
                if previous != migration.sha256:
                    raise RuntimeError(f"Applied migration checksum changed: {migration.version}")
                continue

            unmanaged_baseline = position == 0 and all(core_state)
            if not unmanaged_baseline:
                cursor.execute(migration.path.read_text(encoding="utf-8"))
            cursor.execute(
                "INSERT INTO schema_migrations (version, sha256) VALUES (%s, %s)",
                (migration.version, migration.sha256),
            )
            applied_now.append(migration.version)
    return applied_now


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply Elexion PostgreSQL migrations")
    parser.add_argument("--root", type=Path, default=Path("/app/postgres"))
    args = parser.parse_args()
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is required")
    applied = migrate(dsn, args.root)
    print("Applied migrations: " + (", ".join(applied) if applied else "none"))


if __name__ == "__main__":
    main()
