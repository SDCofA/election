from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import psycopg
from psycopg.types.json import Jsonb


@dataclass(frozen=True)
class AdapterCheckpoint:
    adapter_id: str
    scope_id: str
    parser_version: str
    source_snapshot_sha256: str
    payload: dict


@dataclass(frozen=True)
class AdapterHealthEvent:
    adapter_id: str
    scope_id: str
    status: str
    failure_kind: str | None = None
    message: str | None = None


class CheckpointStore(Protocol):
    def load(self, adapter_id: str, scope_id: str) -> AdapterCheckpoint | None: ...

    def save(self, checkpoint: AdapterCheckpoint) -> None: ...

    def record_failure(
        self,
        adapter_id: str,
        scope_id: str,
        failure_kind: str,
        message: str,
    ) -> None: ...


class MemoryCheckpointStore:
    def __init__(self) -> None:
        self._values: dict[tuple[str, str], AdapterCheckpoint] = {}
        self.events: list[AdapterHealthEvent] = []

    def load(self, adapter_id: str, scope_id: str) -> AdapterCheckpoint | None:
        return self._values.get((adapter_id, scope_id))

    def save(self, checkpoint: AdapterCheckpoint) -> None:
        self._values[(checkpoint.adapter_id, checkpoint.scope_id)] = checkpoint
        self.events.append(
            AdapterHealthEvent(checkpoint.adapter_id, checkpoint.scope_id, "success")
        )

    def record_failure(
        self,
        adapter_id: str,
        scope_id: str,
        failure_kind: str,
        message: str,
    ) -> None:
        self.events.append(
            AdapterHealthEvent(adapter_id, scope_id, "failure", failure_kind, message)
        )


class PostgresCheckpointStore:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def load(self, adapter_id: str, scope_id: str) -> AdapterCheckpoint | None:
        with psycopg.connect(self.dsn) as connection:
            row = connection.execute(
                """
                SELECT parser_version, source_snapshot_sha256, payload
                FROM adapter_checkpoints WHERE adapter_id = %s AND scope_id = %s
                """,
                (adapter_id, scope_id),
            ).fetchone()
        if row is None:
            return None
        return AdapterCheckpoint(
            adapter_id=adapter_id,
            scope_id=scope_id,
            parser_version=row[0],
            source_snapshot_sha256=row[1],
            payload=row[2],
        )

    def save(self, checkpoint: AdapterCheckpoint) -> None:
        with psycopg.connect(self.dsn) as connection, connection.transaction():
            connection.execute(
                """
                INSERT INTO adapter_checkpoints (
                  adapter_id, scope_id, parser_version, source_snapshot_sha256, payload
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (adapter_id, scope_id) DO UPDATE SET
                  parser_version = EXCLUDED.parser_version,
                  source_snapshot_sha256 = EXCLUDED.source_snapshot_sha256,
                  payload = EXCLUDED.payload,
                  updated_at = now()
                WHERE adapter_checkpoints.source_snapshot_sha256
                      IS DISTINCT FROM EXCLUDED.source_snapshot_sha256
                   OR adapter_checkpoints.parser_version IS DISTINCT FROM EXCLUDED.parser_version
                """,
                (
                    checkpoint.adapter_id,
                    checkpoint.scope_id,
                    checkpoint.parser_version,
                    checkpoint.source_snapshot_sha256,
                    Jsonb(checkpoint.payload),
                ),
            )
            connection.execute(
                """
                INSERT INTO adapter_health_events (adapter_id, scope_id, status)
                VALUES (%s, %s, 'success')
                """,
                (checkpoint.adapter_id, checkpoint.scope_id),
            )

    def record_failure(
        self,
        adapter_id: str,
        scope_id: str,
        failure_kind: str,
        message: str,
    ) -> None:
        with psycopg.connect(self.dsn) as connection, connection.transaction():
            connection.execute(
                """
                INSERT INTO adapter_health_events (
                  adapter_id, scope_id, status, failure_kind, details
                ) VALUES (%s, %s, 'failure', %s, %s)
                """,
                (adapter_id, scope_id, failure_kind, Jsonb({"message": message})),
            )
