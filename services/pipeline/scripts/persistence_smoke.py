from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from elexion_pipeline.adapters.dawum import DawumPoll, DawumPollBatch
from elexion_pipeline.adapters.official_calendar import OfficialCalendarBatch
from elexion_pipeline.adapters.official_results import OfficialResultBatch, OfficialResultRecord
from elexion_pipeline.checkpoint import AdapterCheckpoint, PostgresCheckpointStore
from elexion_pipeline.domain import RawSnapshot
from elexion_pipeline.features import FeatureObservation, FeatureSpec, build_feature_snapshot
from elexion_pipeline.persistence import (
    persist_calendar_batch,
    persist_canonical_batch,
    persist_forecast_bundles,
    persist_official_result_batch,
    persist_poll_batches,
    persist_source_vintage_features,
    record_pipeline_run_event,
)
from elexion_pipeline.registry import SourceRegistry


def main() -> None:
    dsn = os.environ["DATABASE_URL"]
    root = Path(__file__).parents[2]
    pack = json.loads((root / "api" / "app" / "packs" / "us.json").read_text())
    de_pack = json.loads((root / "api" / "app" / "packs" / "de.json").read_text())
    br_pack = json.loads((root / "api" / "app" / "packs" / "br.json").read_text())
    pack["reporting_units"] = [
        {"id": "national", "name": "National", "level": "national"}
    ]
    timestamp = datetime(2026, 8, 9, tzinfo=UTC).isoformat()
    digest = "d" * 64
    batch = {
        "snapshots": [
            {
                "source_id": "world_bank_wdi",
                "source_url": "https://api.worldbank.org/v2/fixture",
                "retrieved_at": timestamp,
                "sha256": digest,
                "byte_count": 2,
                "content_type": "application/json",
                "object_key": f"raw/world_bank_wdi/{digest}.bin",
                "object_uri": f"s3://fixture/{digest}",
                "etag": None,
                "last_modified": None,
                "license_id": "CC-BY-4.0",
                "attribution": "World Bank, World Development Indicators",
                "usage_scope": "Persistence smoke fixture",
            }
        ],
        "observations": [
            {
                "jurisdiction_id": "usa",
                "metric": "world_bank:fixture",
                "observed_at": timestamp,
                "released_at": timestamp,
                "available_at": timestamp,
                "value": 1.0,
                "unit": "index",
                "source_id": "world_bank_wdi",
                "source_snapshot_sha256": digest,
                "revision": 0,
                "dimensions": {"smoke": True},
            }
        ],
    }
    first = persist_canonical_batch(
        dsn, [pack, de_pack, br_pack], batch, SourceRegistry.from_path()
    )
    second = persist_canonical_batch(
        dsn, [pack, de_pack, br_pack], batch, SourceRegistry.from_path()
    )
    if (
        first["observations"] != 1
        or first["source_revisions"] != 1
        or second["observations"] != 0
        or second["source_revisions"] != 0
    ):
        raise SystemExit(f"Persistence is not idempotent: first={first}, second={second}")
    revised_batch = json.loads(json.dumps(batch))
    revised_batch["snapshots"][0]["sha256"] = "e" * 64
    revised_batch["snapshots"][0]["object_key"] = f"raw/world_bank_wdi/{'e' * 64}.bin"
    revised_batch["snapshots"][0]["object_uri"] = f"s3://fixture/{'e' * 64}"
    revised_batch["observations"][0]["source_snapshot_sha256"] = "e" * 64
    revised_batch["observations"][0]["value"] = 2.0
    revised = persist_canonical_batch(dsn, [pack], revised_batch, SourceRegistry.from_path())
    if revised["source_revisions"] != 1 or revised["observations"] != 1:
        raise SystemExit(f"Revised source release was not appended: {revised}")
    with psycopg.connect(dsn) as connection:
        revisions = connection.execute(
            """
            SELECT array_agg(revision ORDER BY revision), count(DISTINCT source_revision_id)
            FROM observations WHERE jurisdiction_id = 'usa' AND metric = 'world_bank:fixture'
            """
        ).fetchone()
    if revisions != ([0, 1], 2):
        raise SystemExit(f"Canonical revision lineage is invalid: {revisions}")
    calendar_digest = "b" * 64
    calendar_batch = OfficialCalendarBatch(
        election_id="br-2026-president",
        election_date=datetime(2026, 10, 4, tzinfo=UTC).date(),
        date_confidence="official",
        status="calendar only",
        released_at=datetime(2026, 2, 26, tzinfo=UTC),
        available_at=datetime(2026, 2, 26, tzinfo=UTC),
        parser_version="calendar-smoke-v1",
        parser_confidence=1,
        source_snapshot=RawSnapshot(
            source_id="brazil_tse",
            source_url="https://www.tse.jus.br/calendar-fixture",
            retrieved_at=datetime(2026, 8, 9, tzinfo=UTC),
            sha256=calendar_digest,
            byte_count=10,
            content_type="text/html",
            object_key=f"raw/brazil_tse/{calendar_digest}.bin",
            object_uri=f"s3://fixture/{calendar_digest}",
            license_id="CC-BY-4.0",
            attribution="Tribunal Superior Eleitoral",
            usage_scope="Calendar persistence smoke fixture",
        ),
    )
    calendar_first = persist_calendar_batch(dsn, calendar_batch, SourceRegistry.from_path())
    calendar_second = persist_calendar_batch(dsn, calendar_batch, SourceRegistry.from_path())
    if calendar_first["inserted"] != 1 or calendar_second["inserted"] != 0:
        raise SystemExit(
            f"Calendar persistence is not idempotent: {calendar_first}, {calendar_second}"
        )
    poll_digest = "c" * 64
    poll_time = datetime(2026, 8, 9, 10, tzinfo=UTC)
    poll_batch = DawumPollBatch(
        source_snapshot=RawSnapshot(
            source_id="dawum_polls",
            source_url="https://api.dawum.de/fixture",
            retrieved_at=poll_time,
            sha256=poll_digest,
            byte_count=10,
            content_type="application/json",
            object_key=f"raw/dawum_polls/{poll_digest}.bin",
            object_uri=f"s3://fixture/{poll_digest}",
            license_id="ODC-ODbL-1.0",
            attribution="dawum.de",
            usage_scope="Poll persistence smoke fixture",
        ),
        parser_version="dawum-smoke-v1",
        parser_confidence=1,
        database_updated_at=poll_time,
        polls=[
            DawumPoll(
                poll_key="smoke-poll",
                election_id="de-next-bundestag",
                pollster="Fixture",
                sponsor="Fixture",
                mode="online",
                fieldwork_start=datetime(2026, 8, 7, tzinfo=UTC),
                fieldwork_end=datetime(2026, 8, 8, tzinfo=UTC),
                released_at=datetime(2026, 8, 8, 18, tzinfo=UTC),
                available_at=datetime(2026, 8, 9, tzinfo=UTC),
                sample_size=1_000,
                shares={"union": 0.30, "afd": 0.25, "spd": 0.20, "greens": 0.15, "left": 0.10},
                raw_party_results={"1": 30, "7": 25, "2": 20, "4": 15, "5": 10},
            )
        ],
    )
    poll_first = persist_poll_batches(dsn, [poll_batch], SourceRegistry.from_path())
    poll_second = persist_poll_batches(dsn, [poll_batch], SourceRegistry.from_path())
    if (
        poll_first["polls"] != 1
        or poll_first["poll_results"] != 5
        or poll_second["source_revisions"] != 0
        or poll_second["polls"] != 0
    ):
        raise SystemExit(f"Poll persistence is not idempotent: {poll_first}, {poll_second}")
    result_digest = "f" * 64
    official_batch = OfficialResultBatch(
        election_id="us-2028-president",
        records=[
            OfficialResultRecord(
                election_id="us-2028-president",
                reporting_unit_id="national",
                contestant_id="dem",
                votes=100,
                reporting_fraction=0.25,
                reported_at=datetime(2026, 8, 9, 10, tzinfo=UTC),
                source_snapshot_sha256=result_digest,
            )
        ],
        parser_confidence=1,
        source_url="https://api.worldbank.org/v2/official-result-fixture",
        retrieved_at=datetime(2026, 8, 9, 10, 0, 5, tzinfo=UTC),
        source_id="world_bank_wdi",
        source_snapshot_uri=f"s3://fixture/{result_digest}",
        source_license_id="CC-BY-4.0",
        source_attribution="World Bank, World Development Indicators",
        source_usage_scope="Official-result persistence smoke fixture",
        source_content_type="application/json",
        source_byte_count=10,
    )
    official_first = persist_official_result_batch(
        dsn,
        official_batch,
        SourceRegistry.from_path().require_approved("world_bank_wdi"),
        "official-result-smoke-v1",
    )
    official_second = persist_official_result_batch(
        dsn,
        official_batch,
        SourceRegistry.from_path().require_approved("world_bank_wdi"),
        "official-result-smoke-v1",
    )
    if official_first["inserted"] != 1 or official_second["inserted"] != 0:
        raise SystemExit(
            f"Official-result persistence is not idempotent: {official_first}, {official_second}"
        )
    with psycopg.connect(dsn) as connection:
        feature_row = connection.execute(
            """
            SELECT o.metric, o.value, o.unit, o.observed_at, o.released_at, o.available_at,
                   o.revision, o.source_revision_id, s.source_key, s.url, s.license
            FROM observations o
            JOIN sources s ON s.id = o.source_id
            WHERE o.jurisdiction_id = 'usa' AND o.metric = 'world_bank:fixture'
            ORDER BY o.revision DESC LIMIT 1
            """
        ).fetchone()
    feature = FeatureObservation(
        metric=feature_row[0],
        value=feature_row[1],
        unit=feature_row[2],
        observed_at=feature_row[3],
        released_at=feature_row[4],
        available_at=feature_row[5],
        revision=feature_row[6],
        source_revision_id=str(feature_row[7]),
        source_key=feature_row[8],
        source_url=feature_row[9],
        license=feature_row[10],
    )
    feature_snapshot = build_feature_snapshot(
        "us-2028-president",
        "usa",
        datetime(2026, 8, 9, tzinfo=UTC),
        [feature],
        (FeatureSpec("fixture", ("world_bank:fixture",)),),
    )
    first_features = persist_source_vintage_features(dsn, [feature_snapshot])
    second_features = persist_source_vintage_features(dsn, [feature_snapshot])
    if first_features != 1 or second_features != 0:
        raise SystemExit("Source-vintage feature persistence is not idempotent")
    checkpoint_store = PostgresCheckpointStore(dsn)
    checkpoint_store.save(
        AdapterCheckpoint(
            adapter_id="calendar-smoke",
            scope_id="usa",
            parser_version="fixture-v1",
            source_snapshot_sha256="f" * 64,
            payload={"records": [{"election_id": "us-2028-president"}]},
        )
    )
    checkpoint = checkpoint_store.load("calendar-smoke", "usa")
    if checkpoint is None or checkpoint.source_snapshot_sha256 != "f" * 64:
        raise SystemExit("Durable adapter checkpoint could not be replayed")
    checkpoint_store.record_failure(
        "calendar-smoke", "usa", "parser_drift", "fixture parser changed"
    )
    if not record_pipeline_run_event(
        dsn, "persistence-smoke-run", "refresh_forecasts", "success"
    ) or record_pipeline_run_event(dsn, "persistence-smoke-run", "refresh_forecasts", "success"):
        raise SystemExit("Pipeline telemetry is not idempotent")
    with psycopg.connect(dsn) as connection:
        health = connection.execute(
            """
            SELECT
              (SELECT count(*) FROM adapter_health_events
               WHERE adapter_id = 'calendar-smoke'),
              (SELECT count(*) FROM pipeline_run_events
               WHERE run_id = 'persistence-smoke-run')
            """
        ).fetchone()
    if health[0] < 2 or health[1] != 1:
        raise SystemExit(f"Operational telemetry persistence is invalid: {health}")
    forecast = {
        "id": "persistence-smoke-snapshot",
        "election_id": "us-2028-president",
        "as_of": timestamp,
        "published_at": timestamp,
        "model_version": "persistence-smoke-1",
        "model_family": "baseline_ensemble",
        "selection_status": "baseline retained",
        "simulation_count": 1_000_000,
        "seed": 42,
        "data_quality": "D",
        "freshness": "fixture",
        "missing_drivers": ["polling"],
        "regional_forecast_supported": False,
        "headline": "Persistence fixture",
        "majority_probability": 0.5,
        "turnout_median": 0.6,
        "drivers": [],
        "input_revision_ids": [],
        "input_provenance": [],
        "provenance": pack["election"]["sources"],
        "outcomes": [
            {
                "contestant_id": "dem",
                "win_probability": 0.5,
                "projected_share": 0.49,
                "share_low": 0.44,
                "share_high": 0.54,
                "projected_seats": 269,
                "seats_low": 240,
                "seats_high": 300,
            },
            {
                "contestant_id": "gop",
                "win_probability": 0.5,
                "projected_share": 0.49,
                "share_low": 0.44,
                "share_high": 0.54,
                "projected_seats": 269,
                "seats_low": 238,
                "seats_high": 298,
            },
            {
                "contestant_id": "other",
                "win_probability": 0.0,
                "projected_share": 0.02,
                "share_low": 0.0,
                "share_high": 0.04,
                "projected_seats": 0,
                "seats_low": 0,
                "seats_high": 0,
            },
        ],
        "coalition_outcomes": [],
    }
    bundles = [{"forecast": forecast, "comparison": {"winner": None}}]
    first_forecast = persist_forecast_bundles(dsn, bundles)
    second_forecast = persist_forecast_bundles(dsn, bundles)
    if first_forecast["forecasts"] != 1 or second_forecast["forecasts"] != 0:
        raise SystemExit(
            "Forecast persistence is not idempotent: "
            f"first={first_forecast}, second={second_forecast}"
        )
    print("canonical persistence smoke passed")


if __name__ == "__main__":
    main()
