from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from typing import Any

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from .adapters.dawum import DawumPollBatch
from .adapters.official_calendar import OfficialCalendarBatch
from .adapters.official_results import OfficialResultBatch
from .domain import SourceDefinition
from .registry import SourceRegistry

UUID_NAMESPACE = uuid.UUID("07b23272-6ca9-4b4c-a374-0a3b194ea4f0")


def database_dsn_from_env() -> str | None:
    if value := os.getenv("DATABASE_URL"):
        return value
    if not os.getenv("POSTGRES_HOST"):
        return None
    return make_conninfo(
        host=os.environ["POSTGRES_HOST"],
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "elexion"),
        user=os.getenv("POSTGRES_USER", "elexion"),
        password=os.getenv("POSTGRES_PASSWORD", ""),
    )


def validate_source_vintage_feature(snapshot: dict) -> list[uuid.UUID]:
    required = {
        "election_id",
        "jurisdiction_id",
        "as_of",
        "schema_version",
        "values",
        "source_revision_ids",
        "content_sha256",
    }
    missing = required - snapshot.keys()
    if missing:
        raise ValueError(f"Feature snapshot missing fields: {sorted(missing)}")
    if snapshot["schema_version"] != "canonical-macro-v1":
        raise ValueError("Unsupported source-vintage feature schema")
    if _content_hash(snapshot["values"]) != snapshot["content_sha256"]:
        raise ValueError("Feature snapshot content hash mismatch")
    revision_ids = [uuid.UUID(value) for value in snapshot["source_revision_ids"]]
    if len(revision_ids) != len(set(revision_ids)):
        raise ValueError("Feature snapshot source revisions must be unique")
    return revision_ids


def persist_source_vintage_features(dsn: str, snapshots: list[dict]) -> int:
    inserted_count = 0
    with psycopg.connect(dsn) as connection, connection.transaction():
        for snapshot in snapshots:
            revision_ids = validate_source_vintage_feature(snapshot)
            if revision_ids:
                verified = connection.execute(
                    """
                    SELECT count(DISTINCT revision.id)
                    FROM source_revisions revision
                    JOIN observations observation ON observation.source_revision_id = revision.id
                    JOIN sources source ON source.id = revision.source_id
                    WHERE revision.id = ANY(%s)
                      AND observation.jurisdiction_id = %s
                      AND observation.available_at <= %s
                      AND observation.observed_at <= %s
                      AND source.retrieved_at <= %s
                    """,
                    (
                        revision_ids,
                        snapshot["jurisdiction_id"],
                        snapshot["as_of"],
                        snapshot["as_of"],
                        snapshot["as_of"],
                    ),
                ).fetchone()
                if verified is None or verified[0] != len(revision_ids):
                    raise ValueError("Feature snapshot revision lineage is invalid")
            feature_id = uuid.uuid5(
                UUID_NAMESPACE,
                (
                    f"canonical-feature:{snapshot['election_id']}:"
                    f"{snapshot['as_of']}:{snapshot['content_sha256']}"
                ),
            )
            inserted = connection.execute(
                """
                INSERT INTO feature_snapshots (
                  id, election_id, as_of, schema_version, values, source_revision_ids,
                  content_sha256
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (election_id, as_of, schema_version) DO NOTHING
                RETURNING id
                """,
                (
                    feature_id,
                    snapshot["election_id"],
                    snapshot["as_of"],
                    snapshot["schema_version"],
                    Jsonb(snapshot["values"]),
                    revision_ids,
                    snapshot["content_sha256"],
                ),
            ).fetchone()
            inserted_count += int(inserted is not None)
    return inserted_count


def record_pipeline_run_event(
    dsn: str,
    run_id: str,
    job_name: str,
    status: str,
    details: dict | None = None,
) -> bool:
    if status not in {"success", "failure"}:
        raise ValueError("Pipeline run status must be success or failure")
    with psycopg.connect(dsn) as connection, connection.transaction():
        inserted = connection.execute(
            """
            INSERT INTO pipeline_run_events (run_id, job_name, status, details)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (run_id, status) DO NOTHING
            RETURNING id
            """,
            (run_id, job_name, status, Jsonb(details or {})),
        ).fetchone()
    return inserted is not None


def persist_official_result_batch(
    dsn: str,
    batch: OfficialResultBatch,
    source: SourceDefinition,
    parser_version: str,
) -> dict[str, int | str]:
    if batch.fallback_used:
        raise ValueError("Last-known-good official results cannot be persisted as a fresh batch")
    if batch.source_id != source.id or not source.approved:
        raise ValueError("Official-result snapshot does not match an approved source")
    keys = {(item.reporting_unit_id, item.contestant_id) for item in batch.records}
    if len(keys) != len(batch.records):
        raise ValueError("Official-result batch keys must be unique")
    with psycopg.connect(dsn) as connection, connection.transaction():
        source_row = connection.execute(
            """
            WITH inserted AS (
              INSERT INTO sources (
                source_key, label, url, authority, license, license_url, attribution,
                usage_scope, license_approved, retrieved_at, content_sha256, object_uri,
                parser_version, parser_confidence, metadata
              ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true, %s, %s, %s, %s, %s, %s)
              ON CONFLICT (source_key, content_sha256) DO NOTHING
              RETURNING id
            )
            SELECT id FROM inserted
            UNION ALL
            SELECT id FROM sources WHERE source_key = %s AND content_sha256 = %s
            LIMIT 1
            """,
            (
                source.id,
                source.name,
                batch.source_url,
                source.authority,
                batch.source_license_id,
                source.license_url,
                batch.source_attribution,
                batch.source_usage_scope,
                batch.retrieved_at,
                batch.records[0].source_snapshot_sha256,
                batch.source_snapshot_uri,
                parser_version,
                batch.parser_confidence,
                Jsonb(
                    {
                        "byte_count": batch.source_byte_count,
                        "content_type": batch.source_content_type,
                    }
                ),
                source.id,
                batch.records[0].source_snapshot_sha256,
            ),
        ).fetchone()
        if source_row is None:
            raise RuntimeError("Could not resolve official-result source snapshot")
        source_id = source_row[0]

        expected_units = {item.reporting_unit_id for item in batch.records}
        expected_contestants = {item.contestant_id for item in batch.records}
        unit_count = connection.execute(
            """
            SELECT count(*) FROM reporting_units
            WHERE election_id = %s AND id = ANY(%s::text[])
            """,
            (batch.election_id, sorted(expected_units)),
        ).fetchone()
        contestant_count = connection.execute(
            """
            SELECT count(*) FROM contestants
            WHERE election_id = %s AND id = ANY(%s::text[])
            """,
            (batch.election_id, sorted(expected_contestants)),
        ).fetchone()
        if unit_count is None or unit_count[0] != len(expected_units):
            raise ValueError("Official-result batch references unknown reporting units")
        if contestant_count is None or contestant_count[0] != len(expected_contestants):
            raise ValueError("Official-result batch references unknown contestants")

        previous_rows = connection.execute(
            """
            SELECT DISTINCT ON (reporting_unit_id, contestant_id)
              reporting_unit_id, contestant_id, votes, reporting_fraction, reported_at
            FROM official_results
            WHERE election_id = %s
              AND reporting_unit_id = ANY(%s::text[])
              AND contestant_id = ANY(%s::text[])
            ORDER BY reporting_unit_id, contestant_id, reported_at DESC
            """,
            (batch.election_id, sorted(expected_units), sorted(expected_contestants)),
        ).fetchall()
        previous = {(row[0], row[1]): row for row in previous_rows}
        inserted_count = 0
        for item in batch.records:
            old = previous.get((item.reporting_unit_id, item.contestant_id))
            if old is not None:
                if item.reported_at < old[4]:
                    raise ValueError("Official-result timestamp moved backwards in durable store")
                if item.votes < old[2] or item.reporting_fraction < old[3]:
                    raise ValueError("Official-result totals decreased in durable store")
                if item.reported_at == old[4] and (
                    item.votes != old[2] or item.reporting_fraction != old[3]
                ):
                    raise ValueError("Official-result values changed at an existing timestamp")
            inserted = connection.execute(
                """
                INSERT INTO official_results (
                  election_id, reporting_unit_id, contestant_id, votes,
                  reporting_fraction, reported_at, source_id, is_certified
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING contestant_id
                """,
                (
                    item.election_id,
                    item.reporting_unit_id,
                    item.contestant_id,
                    item.votes,
                    item.reporting_fraction,
                    item.reported_at,
                    source_id,
                    item.is_certified,
                ),
            ).fetchone()
            inserted_count += int(inserted is not None)
    return {
        "inserted": inserted_count,
        "record_count": len(batch.records),
        "source_snapshot_sha256": batch.records[0].source_snapshot_sha256,
    }


def persist_poll_batches(
    dsn: str, batches: list[DawumPollBatch], registry: SourceRegistry
) -> dict[str, int | list[str]]:
    counts: dict[str, int | list[str]] = {
        "sources": 0,
        "source_revisions": 0,
        "polls": 0,
        "poll_results": 0,
        "source_revision_ids": [],
    }
    revision_ids: set[str] = set()
    with psycopg.connect(dsn) as connection, connection.transaction():
        for batch in batches:
            snapshot = batch.source_snapshot
            source = registry.require_approved(snapshot.source_id)
            if snapshot.license_id != source.license_id:
                raise ValueError(f"Poll snapshot license conflicts with registry: {source.id}")
            inserted_source = connection.execute(
                """
                INSERT INTO sources (
                  source_key, label, url, authority, license, license_url, attribution,
                  usage_scope, license_approved, retrieved_at, content_sha256, object_uri,
                  parser_version, parser_confidence, metadata
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_key, content_sha256) DO NOTHING
                RETURNING id
                """,
                (
                    source.id,
                    source.name,
                    snapshot.source_url,
                    source.authority,
                    source.license_id,
                    source.license_url,
                    snapshot.attribution,
                    snapshot.usage_scope,
                    snapshot.retrieved_at,
                    snapshot.sha256,
                    snapshot.object_uri,
                    batch.parser_version,
                    batch.parser_confidence,
                    Jsonb(
                        {
                            "byte_count": snapshot.byte_count,
                            "content_type": snapshot.content_type,
                            "etag": snapshot.etag,
                            "last_modified": snapshot.last_modified,
                            "database_updated_at": batch.database_updated_at.isoformat(),
                        }
                    ),
                ),
            ).fetchone()
            counts["sources"] = int(counts["sources"]) + int(inserted_source is not None)
            source_row = (
                inserted_source
                or connection.execute(
                    "SELECT id FROM sources WHERE source_key = %s AND content_sha256 = %s",
                    (source.id, snapshot.sha256),
                ).fetchone()
            )
            if source_row is None:
                raise RuntimeError("Could not resolve poll source snapshot")

            for poll in batch.polls:
                payload = poll.model_dump(mode="json")
                payload_hash = _content_hash(payload)
                source_record_key = f"{poll.election_id}:{poll.poll_key}"
                latest = connection.execute(
                    """
                    SELECT id, revision, payload_sha256
                    FROM source_revisions
                    WHERE source_key = %s AND source_record_key = %s
                    ORDER BY revision DESC LIMIT 1
                    """,
                    (source.id, source_record_key),
                ).fetchone()
                if latest is not None and latest[2] == payload_hash:
                    revision_id, revision = latest[0], latest[1]
                else:
                    revision = 0 if latest is None else latest[1] + 1
                    revision_row = connection.execute(
                        """
                        INSERT INTO source_revisions (
                          source_id, source_key, source_record_key, revision, observed_at,
                          released_at, available_at, payload, payload_sha256
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            source_row[0],
                            source.id,
                            source_record_key,
                            revision,
                            poll.fieldwork_end,
                            poll.released_at,
                            poll.available_at,
                            Jsonb(payload),
                            payload_hash,
                        ),
                    ).fetchone()
                    if revision_row is None:
                        raise RuntimeError("Could not append poll source revision")
                    revision_id = revision_row[0]
                    counts["source_revisions"] = int(counts["source_revisions"]) + 1
                revision_ids.add(str(revision_id))
                inserted_poll = connection.execute(
                    """
                    INSERT INTO polls (
                      id, election_id, poll_key, revision, pollster, sponsor, population,
                      mode, fieldwork_start, fieldwork_end, released_at, available_at,
                      sample_size, source_id, parser_version, parser_confidence, metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    RETURNING id
                    """,
                    (
                        revision_id,
                        poll.election_id,
                        poll.poll_key,
                        revision,
                        poll.pollster,
                        poll.sponsor,
                        poll.population,
                        poll.mode,
                        poll.fieldwork_start,
                        poll.fieldwork_end,
                        poll.released_at,
                        poll.available_at,
                        poll.sample_size,
                        source_row[0],
                        batch.parser_version,
                        batch.parser_confidence,
                        Jsonb(
                            {
                                "raw_party_results": poll.raw_party_results,
                                "date_precision": poll.date_precision,
                            }
                        ),
                    ),
                ).fetchone()
                counts["polls"] = int(counts["polls"]) + int(inserted_poll is not None)
                for contestant_id, share in poll.shares.items():
                    inserted_result = connection.execute(
                        """
                        INSERT INTO poll_results (poll_id, election_id, contestant_id, share)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (poll_id, contestant_id) DO NOTHING
                        RETURNING contestant_id
                        """,
                        (revision_id, poll.election_id, contestant_id, share),
                    ).fetchone()
                    counts["poll_results"] = int(counts["poll_results"]) + int(
                        inserted_result is not None
                    )
    counts["source_revision_ids"] = sorted(revision_ids)
    return counts


def persist_calendar_batch(
    dsn: str,
    batch: OfficialCalendarBatch,
    registry: SourceRegistry,
) -> dict[str, int | str]:
    if batch.fallback_used:
        raise ValueError("Last-known-good calendar cannot be persisted as a fresh revision")
    snapshot = batch.source_snapshot
    source = registry.require_approved(snapshot.source_id)
    if source.authority != "official":
        raise ValueError("Calendar revisions require an official election authority")
    if snapshot.license_id != source.license_id:
        raise ValueError(f"Calendar snapshot license conflicts with registry: {source.id}")
    payload = {
        "election_id": batch.election_id,
        "election_date": batch.election_date.isoformat(),
        "date_confidence": batch.date_confidence,
        "status": batch.status,
    }
    payload_hash = _content_hash(payload)
    record_key = f"{batch.election_id}:calendar"
    with psycopg.connect(dsn) as connection, connection.transaction():
        source_row = connection.execute(
            """
            WITH inserted AS (
              INSERT INTO sources (
                source_key, label, url, authority, license, license_url, attribution,
                usage_scope, license_approved, retrieved_at, content_sha256, object_uri,
                parser_version, parser_confidence, metadata
              ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true, %s, %s, %s, %s, %s, %s)
              ON CONFLICT (source_key, content_sha256) DO NOTHING
              RETURNING id
            )
            SELECT id FROM inserted
            UNION ALL
            SELECT id FROM sources WHERE source_key = %s AND content_sha256 = %s
            LIMIT 1
            """,
            (
                source.id,
                source.name,
                snapshot.source_url,
                source.authority,
                source.license_id,
                source.license_url,
                snapshot.attribution,
                snapshot.usage_scope,
                snapshot.retrieved_at,
                snapshot.sha256,
                snapshot.object_uri,
                batch.parser_version,
                batch.parser_confidence,
                Jsonb(
                    {
                        "byte_count": snapshot.byte_count,
                        "content_type": snapshot.content_type,
                        "etag": snapshot.etag,
                        "last_modified": snapshot.last_modified,
                    }
                ),
                source.id,
                snapshot.sha256,
            ),
        ).fetchone()
        if source_row is None:
            raise RuntimeError("Could not resolve calendar source snapshot")
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"{source.id}:{record_key}",),
        )
        latest = connection.execute(
            """
            SELECT id, revision, payload_sha256
            FROM source_revisions
            WHERE source_key = %s AND source_record_key = %s
            ORDER BY revision DESC LIMIT 1
            """,
            (source.id, record_key),
        ).fetchone()
        if latest is not None and latest[2] == payload_hash:
            return {
                "inserted": 0,
                "revision": latest[1],
                "source_revision_id": str(latest[0]),
            }
        revision = 0 if latest is None else latest[1] + 1
        revision_row = connection.execute(
            """
            INSERT INTO source_revisions (
              source_id, source_key, source_record_key, revision, observed_at,
              released_at, available_at, payload, payload_sha256
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                source_row[0],
                source.id,
                record_key,
                revision,
                batch.released_at,
                batch.released_at,
                batch.available_at,
                Jsonb(payload),
                payload_hash,
            ),
        ).fetchone()
        if revision_row is None:
            raise RuntimeError("Could not append calendar source revision")
        inserted = connection.execute(
            """
            INSERT INTO calendar_revisions (
              id, election_id, revision, election_date, date_confidence, status,
              released_at, available_at, parser_version, parser_confidence,
              metadata
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                revision_row[0],
                batch.election_id,
                revision,
                batch.election_date,
                batch.date_confidence,
                batch.status,
                batch.released_at,
                batch.available_at,
                batch.parser_version,
                batch.parser_confidence,
                Jsonb({"source_snapshot_sha256": snapshot.sha256}),
            ),
        ).fetchone()
        if inserted is None:
            raise RuntimeError("Could not persist calendar revision")
    return {
        "inserted": 1,
        "revision": revision,
        "source_revision_id": str(revision_row[0]),
    }


def persist_canonical_batch(
    dsn: str,
    packs: list[dict],
    macro_batch: dict[str, list[dict]],
    registry: SourceRegistry,
) -> dict[str, int]:
    counts = {
        "jurisdictions": 0,
        "elections": 0,
        "contestants": 0,
        "reporting_units": 0,
        "sources": 0,
        "source_revisions": 0,
        "observations": 0,
    }
    with psycopg.connect(dsn) as connection, connection.transaction():
        for pack in packs:
            jurisdiction = pack["jurisdiction"]
            inserted = connection.execute(
                """
                INSERT INTO jurisdictions (
                  id, iso3, name, region, eligibility, is_exception, forecast_enabled
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                RETURNING id
                """,
                (
                    jurisdiction["id"],
                    jurisdiction.get("iso3"),
                    jurisdiction["name"],
                    jurisdiction["region"],
                    jurisdiction["eligibility"],
                    jurisdiction.get("is_exception", False),
                    jurisdiction.get("forecast_enabled", True),
                ),
            ).fetchone()
            counts["jurisdictions"] += int(inserted is not None)

            election = pack["election"]
            inserted = connection.execute(
                """
                INSERT INTO elections (
                  id, jurisdiction_id, name, election_date, date_confidence, system,
                  seats_total, majority, status, valid_from
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                RETURNING id
                """,
                (
                    election["id"],
                    election["jurisdiction_id"],
                    election["name"],
                    election["election_date"],
                    election["date_confidence"],
                    election["system"],
                    election.get("seats_total"),
                    election.get("majority"),
                    election["status"],
                    election["last_updated"],
                ),
            ).fetchone()
            counts["elections"] += int(inserted is not None)
            for contestant in election["contestants"]:
                inserted = connection.execute(
                    """
                    INSERT INTO contestants (
                      id, election_id, name, short_name, color, incumbent, metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (election_id, id) DO NOTHING
                    RETURNING id
                    """,
                    (
                        contestant["id"],
                        election["id"],
                        contestant["name"],
                        contestant["short_name"],
                        contestant["color"],
                        contestant.get("incumbent", False),
                        Jsonb(
                            {
                                key: value
                                for key, value in contestant.items()
                                if key not in {"id", "name", "short_name", "color", "incumbent"}
                            }
                        ),
                    ),
                ).fetchone()
                counts["contestants"] += int(inserted is not None)
            pending_units = list(pack.get("reporting_units", []))
            inserted_unit_ids: set[str] = set()
            while pending_units:
                ready = [
                    unit
                    for unit in pending_units
                    if unit.get("parent_id") is None or unit["parent_id"] in inserted_unit_ids
                ]
                if not ready:
                    raise ValueError("Reporting-unit hierarchy contains a cycle or missing parent")
                for unit in ready:
                    inserted = connection.execute(
                        """
                        INSERT INTO reporting_units (
                          id, election_id, parent_id, name, level, seats
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (election_id, id) DO NOTHING
                        RETURNING id
                        """,
                        (
                            unit["id"],
                            election["id"],
                            unit.get("parent_id"),
                            unit["name"],
                            unit["level"],
                            unit.get("seats"),
                        ),
                    ).fetchone()
                    counts["reporting_units"] += int(inserted is not None)
                    inserted_unit_ids.add(unit["id"])
                    pending_units.remove(unit)

        snapshot_ids: dict[tuple[str, str], Any] = {}
        for snapshot in macro_batch["snapshots"]:
            source = registry.get(snapshot["source_id"])
            if not source.approved:
                raise PermissionError(f"Canonical persistence rejected blocked source: {source.id}")
            if snapshot["license_id"] != source.license_id:
                raise ValueError(f"Snapshot license conflicts with registry: {source.id}")
            values = (
                snapshot["source_id"],
                source.name,
                snapshot["source_url"],
                source.authority,
                snapshot["license_id"],
                source.license_url,
                snapshot["attribution"],
                snapshot["usage_scope"],
                source.approved,
                snapshot["retrieved_at"],
                snapshot["sha256"],
                snapshot["object_uri"],
                f"{snapshot['source_id']}-v1",
                1.0,
                Jsonb(
                    {
                        "byte_count": snapshot["byte_count"],
                        "content_type": snapshot["content_type"],
                        "etag": snapshot.get("etag"),
                        "last_modified": snapshot.get("last_modified"),
                    }
                ),
            )
            row = connection.execute(
                """
                INSERT INTO sources (
                  source_key, label, url, authority, license, license_url, attribution,
                  usage_scope, license_approved, retrieved_at, content_sha256, object_uri,
                  parser_version, parser_confidence, metadata
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_key, content_sha256) DO NOTHING
                RETURNING id
                """,
                values,
            ).fetchone()
            source_inserted = row is not None
            if row is None:
                row = connection.execute(
                    "SELECT id FROM sources WHERE source_key = %s AND content_sha256 = %s",
                    (snapshot["source_id"], snapshot["sha256"]),
                ).fetchone()
            if row is None:
                raise RuntimeError("Could not resolve persisted raw source snapshot")
            snapshot_ids[(snapshot["source_id"], snapshot["sha256"])] = row[0]
            counts["sources"] += int(source_inserted)

        for observation in macro_batch["observations"]:
            source_id = snapshot_ids[
                (observation["source_id"], observation["source_snapshot_sha256"])
            ]
            payload = {
                "jurisdiction_id": observation["jurisdiction_id"],
                "metric": observation["metric"],
                "value": observation["value"],
                "unit": observation["unit"],
                "dimensions": observation["dimensions"],
            }
            source_record_key = (
                f"{observation['jurisdiction_id']}:{observation['metric']}:"
                f"{observation['observed_at']}"
            )
            payload_hash = _content_hash(payload)
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"{observation['source_id']}:{source_record_key}",),
            )
            revision_row = connection.execute(
                """
                SELECT id, revision, source_id FROM source_revisions
                WHERE source_key = %s AND source_record_key = %s AND payload_sha256 = %s
                ORDER BY revision DESC LIMIT 1
                """,
                (observation["source_id"], source_record_key, payload_hash),
            ).fetchone()
            revision_inserted = False
            if revision_row is None:
                next_revision_row = connection.execute(
                    """
                    SELECT COALESCE(max(revision), -1) + 1 FROM source_revisions
                    WHERE source_key = %s AND source_record_key = %s
                    """,
                    (observation["source_id"], source_record_key),
                ).fetchone()
                if next_revision_row is None:
                    raise RuntimeError("Could not allocate canonical source revision")
                revision_number = int(next_revision_row[0])
                revision_row = connection.execute(
                    """
                INSERT INTO source_revisions (
                  source_id, source_key, source_record_key, revision, observed_at, released_at,
                  available_at, payload, payload_sha256
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, revision, source_id
                """,
                    (
                        source_id,
                        observation["source_id"],
                        source_record_key,
                        revision_number,
                        observation["observed_at"],
                        observation["released_at"],
                        observation["available_at"],
                        Jsonb(payload),
                        payload_hash,
                    ),
                ).fetchone()
                revision_inserted = revision_row is not None
            if revision_row is None:
                raise RuntimeError("Could not resolve canonical source revision")
            counts["source_revisions"] += int(revision_inserted)
            inserted = connection.execute(
                """
                INSERT INTO observations (
                  jurisdiction_id, metric, observed_at, released_at, available_at,
                  value, unit, source_id, source_revision_id, revision, dimensions
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING id
                """,
                (
                    observation["jurisdiction_id"],
                    observation["metric"],
                    observation["observed_at"],
                    observation["released_at"],
                    observation["available_at"],
                    observation["value"],
                    observation["unit"],
                    revision_row[2],
                    revision_row[0],
                    revision_row[1],
                    Jsonb(observation["dimensions"]),
                ),
            ).fetchone()
            counts["observations"] += int(inserted is not None)
    return counts


def _content_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def persist_forecast_bundles(dsn: str, bundles: list[dict]) -> dict[str, int]:
    counts = {
        "features": 0,
        "models": 0,
        "simulations": 0,
        "forecasts": 0,
        "outcomes": 0,
        "coalitions": 0,
    }
    configured_code_sha = os.getenv("GITHUB_SHA", "")
    with psycopg.connect(dsn) as connection, connection.transaction():
        for bundle in bundles:
            forecast = bundle["forecast"]
            comparison = bundle["comparison"]
            revision_ids = [str(uuid.UUID(value)) for value in forecast["input_revision_ids"]]
            if len(revision_ids) != len(set(revision_ids)):
                raise ValueError("Feature snapshot input revision IDs must be unique")
            input_source_keys = sorted(
                {source["source_id"] for source in forecast["input_provenance"]}
            )
            if revision_ids:
                verified = connection.execute(
                    """
                    SELECT count(*)
                    FROM source_revisions revision
                    JOIN sources source ON source.id = revision.source_id
                    WHERE revision.id = ANY(%s::uuid[])
                      AND source.source_key = ANY(%s::text[])
                      AND revision.available_at <= %s
                      AND source.retrieved_at <= %s
                    """,
                    (
                        revision_ids,
                        input_source_keys,
                        forecast["as_of"],
                        forecast["as_of"],
                    ),
                ).fetchone()
                if verified is None or verified[0] != len(set(revision_ids)):
                    raise ValueError(
                        "Feature snapshot contains unknown, future, or provenance-mismatched revisions"
                    )
            model_id = f"{forecast['model_version']}:{forecast['model_family']}"
            code_sha = (
                configured_code_sha
                if re.fullmatch(r"[0-9a-f]{40}", configured_code_sha)
                else hashlib.sha1(forecast["model_version"].encode()).hexdigest()
            )
            feature_values = {
                "drivers": forecast["drivers"],
                "missing_drivers": forecast["missing_drivers"],
                "input_revision_ids": forecast["input_revision_ids"],
                "input_provenance": forecast["input_provenance"],
            }
            feature_hash = _content_hash(feature_values)
            feature_id = uuid.uuid5(UUID_NAMESPACE, f"feature:{forecast['id']}:{feature_hash}")
            simulation_id = uuid.uuid5(UUID_NAMESPACE, f"simulation:{forecast['id']}")

            inserted = connection.execute(
                """
                INSERT INTO model_versions (
                  id, family, code_sha, config_sha, trained_through, promoted_at,
                  selection_evidence
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                RETURNING id
                """,
                (
                    model_id,
                    forecast["model_family"],
                    code_sha,
                    _content_hash(
                        {
                            "model_version": forecast["model_version"],
                            "simulation_count": forecast["simulation_count"],
                        }
                    ),
                    forecast["as_of"],
                    forecast["published_at"],
                    Jsonb(comparison),
                ),
            ).fetchone()
            counts["models"] += int(inserted is not None)

            inserted = connection.execute(
                """
                INSERT INTO feature_snapshots (
                  id, election_id, as_of, schema_version, values, source_revision_ids,
                  content_sha256
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                RETURNING id
                """,
                (
                    feature_id,
                    forecast["election_id"],
                    forecast["as_of"],
                    "forecast-api-v1",
                    Jsonb(feature_values),
                    revision_ids,
                    feature_hash,
                ),
            ).fetchone()
            counts["features"] += int(inserted is not None)

            output_hash = _content_hash(forecast)
            inserted = connection.execute(
                """
                INSERT INTO simulation_runs (
                  id, election_id, model_version_id, feature_snapshot_id, started_at,
                  completed_at, simulation_count, seed, engine, input_sha256,
                  output_sha256, status, validation
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                RETURNING id
                """,
                (
                    simulation_id,
                    forecast["election_id"],
                    model_id,
                    feature_id,
                    forecast["as_of"],
                    forecast["published_at"],
                    forecast["simulation_count"],
                    forecast["seed"],
                    forecast["model_family"],
                    feature_hash,
                    output_hash,
                    "validated",
                    Jsonb(
                        {
                            "selection_status": forecast["selection_status"],
                            "regional_forecast_supported": forecast["regional_forecast_supported"],
                        }
                    ),
                ),
            ).fetchone()
            counts["simulations"] += int(inserted is not None)

            inserted = connection.execute(
                """
                INSERT INTO forecast_snapshots (
                  id, election_id, model_version_id, simulation_run_id, as_of,
                  published_at, simulation_count, seed, data_quality, freshness,
                  headline, majority_probability, turnout_median, source_manifest
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                RETURNING id
                """,
                (
                    forecast["id"],
                    forecast["election_id"],
                    model_id,
                    simulation_id,
                    forecast["as_of"],
                    forecast["published_at"],
                    forecast["simulation_count"],
                    forecast["seed"],
                    forecast["data_quality"],
                    forecast["freshness"],
                    forecast["headline"],
                    forecast["majority_probability"],
                    forecast["turnout_median"],
                    Jsonb(
                        {
                            "input_provenance": forecast["input_provenance"],
                            "provenance": forecast["provenance"],
                        }
                    ),
                ),
            ).fetchone()
            counts["forecasts"] += int(inserted is not None)

            for outcome in forecast["outcomes"]:
                inserted = connection.execute(
                    """
                    INSERT INTO forecast_outcomes (
                      snapshot_id, election_id, contestant_id, win_probability,
                      projected_share, share_low, share_high, projected_seats,
                      seats_low, seats_high
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (snapshot_id, contestant_id) DO NOTHING
                    RETURNING contestant_id
                    """,
                    (
                        forecast["id"],
                        forecast["election_id"],
                        outcome["contestant_id"],
                        outcome["win_probability"],
                        outcome["projected_share"],
                        outcome["share_low"],
                        outcome["share_high"],
                        outcome["projected_seats"],
                        outcome["seats_low"],
                        outcome["seats_high"],
                    ),
                ).fetchone()
                counts["outcomes"] += int(inserted is not None)

            for coalition in forecast["coalition_outcomes"]:
                coalition_key = "+".join(sorted(coalition["member_ids"]))
                inserted = connection.execute(
                    """
                    INSERT INTO forecast_coalition_outcomes (
                      snapshot_id, election_id, coalition_key, member_ids,
                      majority_probability, seats_median, seats_low, seats_high
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (snapshot_id, coalition_key) DO NOTHING
                    RETURNING coalition_key
                    """,
                    (
                        forecast["id"],
                        forecast["election_id"],
                        coalition_key,
                        sorted(coalition["member_ids"]),
                        coalition["majority_probability"],
                        coalition["seats_median"],
                        coalition["seats_low"],
                        coalition["seats_high"],
                    ),
                ).fetchone()
                counts["coalitions"] += int(inserted is not None)
    return counts
