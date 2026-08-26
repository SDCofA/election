import asyncio
import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import nats
from dagster import (
    AssetExecutionContext,
    AssetSelection,
    DagsterRunStatus,
    DefaultSensorStatus,
    Definitions,
    RunStatusSensorContext,
    ScheduleDefinition,
    asset,
    define_asset_job,
    run_status_sensor,
)

from .adapters.dawum import DawumAdapter, DawumPollBatch
from .adapters.eurostat import EurostatAdapter
from .adapters.http import HttpSnapshotFetcher
from .adapters.oecd import OecdAdapter
from .adapters.official_calendar import OfficialCalendarAdapter, OfficialCalendarConfig
from .adapters.official_results import OfficialResultAdapter
from .adapters.retired_event import RetiredEventAdapter
from .adapters.vdem import VDemAdapter
from .adapters.world_bank import WorldBankAdapter
from .checkpoint import AdapterCheckpoint, PostgresCheckpointStore
from .features import build_database_feature_snapshot
from .live_results import select_active_feeds, validated_feed_config
from .persistence import (
    database_dsn_from_env,
    persist_calendar_batch,
    persist_canonical_batch,
    persist_forecast_bundles,
    persist_official_result_batch,
    persist_poll_batches,
    persist_source_vintage_features,
    record_pipeline_run_event,
)
from .registry import SourceRegistry
from .storage import SnapshotWriter, object_store_from_env

REPO_ROOT = Path(__file__).parents[3]
PACKS_DIR = Path(
    os.getenv("ELEXION_PACKS_DIR", str(REPO_ROOT / "services" / "api" / "app" / "packs"))
)
RAW_ROOT = Path(os.getenv("ELEXION_RAW_ROOT", str(REPO_ROOT / ".data" / "objects")))
API_INTERNAL_URL = os.getenv("ELEXION_API_INTERNAL_URL", "http://api:8000").rstrip("/")
INTERNAL_TOKEN = os.getenv("ELEXION_INTERNAL_TOKEN")
NATS_URL = os.getenv("NATS_URL")
REQUIRED_ELECTION_FIELDS = {"id", "jurisdiction_id", "name", "election_date", "system", "sources"}
REQUIRED_PACK_FIELDS = {"jurisdiction", "election", "rules", "source_adapters"}


def _fetcher() -> HttpSnapshotFetcher:
    registry = SourceRegistry.from_path()
    return HttpSnapshotFetcher(registry, SnapshotWriter(object_store_from_env(RAW_ROOT)))


@asset(group_name="governance")
def source_policy(context: AssetExecutionContext) -> dict:
    registry = SourceRegistry.from_path()
    approved = [source.id for source in registry.approved()]
    blocked = [source.id for source in registry.blocked()]
    context.add_output_metadata({"approved_count": len(approved), "blocked_count": len(blocked)})
    return {"approved": approved, "blocked": blocked}


@asset(group_name="catalog", compute_kind="filesystem")
def jurisdiction_packs(context: AssetExecutionContext) -> list[dict]:
    packs = []
    registry = SourceRegistry.from_path()
    approved_adapters = 0
    blocked_adapters = 0
    for path in sorted(PACKS_DIR.rglob("*.json")):
        raw = path.read_bytes()
        data = json.loads(raw)
        missing_pack_fields = REQUIRED_PACK_FIELDS - set(data)
        if missing_pack_fields:
            raise ValueError(f"{path.name} missing pack fields: {sorted(missing_pack_fields)}")
        missing = REQUIRED_ELECTION_FIELDS - set(data["election"])
        if missing:
            raise ValueError(f"{path.name} missing election fields: {sorted(missing)}")
        if data["rules"]["engine"] != data["election"]["system"]:
            raise ValueError(f"{path.name} rule engine does not match election system")
        if not data["jurisdiction"].get("forecast_enabled", True):
            coverage = data["jurisdiction"].get("coverage_status")
            if coverage not in {"calendar_only", "mechanics_blocked"}:
                raise ValueError(f"{path.name} disabled forecast requires explicit coverage status")
            if not data["jurisdiction"].get("blocking_reasons"):
                raise ValueError(f"{path.name} disabled forecast requires blocking reasons")
            if coverage == "calendar_only" and data["election"]["contestants"]:
                raise ValueError(f"{path.name} calendar-only pack cannot declare contestants")
        adapter_source_ids = {adapter["source_id"] for adapter in data["source_adapters"]}
        for adapter in data["source_adapters"]:
            if adapter["status"] == "reference_only_no_ingestion":
                blocked_adapters += 1
                continue
            source = registry.get(adapter["source_id"])
            configured_approved = adapter["status"] == "approved"
            if configured_approved != source.approved:
                raise ValueError(f"{path.name} adapter status conflicts with source policy")
            approved_adapters += int(configured_approved)
            blocked_adapters += int(not configured_approved)
        for citation in data["election"]["sources"]:
            source_id = citation.get("source_id")
            if source_id not in adapter_source_ids:
                raise ValueError(f"{path.name} citation is not backed by a configured adapter")
            adapter = next(
                item for item in data["source_adapters"] if item["source_id"] == source_id
            )
            if adapter["status"] == "reference_only_no_ingestion":
                if citation.get("license") != "LINK-ONLY-NO-INGESTION":
                    raise ValueError(f"{path.name} reference-only citation must not ingest")
                if not citation.get("url", "").startswith("https://"):
                    raise ValueError(f"{path.name} reference-only citation must use HTTPS")
                continue
            source = registry.get(source_id)
            if citation.get("license") != source.license_id:
                raise ValueError(f"{path.name} citation license conflicts with source policy")
            if citation.get("license_url") != source.license_url:
                raise ValueError(f"{path.name} citation license URL conflicts with source policy")
        contestant_ids = {item["id"] for item in data["election"]["contestants"]}
        citation_source_ids = {item["source_id"] for item in data["election"]["sources"]}
        for feed in data.get("calendar_feeds", []):
            config = OfficialCalendarConfig.model_validate(
                {**feed, "election_id": data["election"]["id"]}
            )
            adapter = next(
                (item for item in data["source_adapters"] if item["source_id"] == config.source_id),
                None,
            )
            source = registry.require_approved(config.source_id)
            if source.authority != "official":
                raise ValueError(f"{path.name} calendar source is not an election authority")
            if adapter is None or adapter["status"] != "approved":
                raise ValueError(f"{path.name} calendar feed lacks an approved pack adapter")
            if config.source_id not in citation_source_ids:
                raise ValueError(f"{path.name} calendar feed lacks election provenance")
            if config.election_date.isoformat() != data["election"]["election_date"]:
                raise ValueError(f"{path.name} calendar feed conflicts with election date")
        for feed in data.get("poll_feeds", []):
            required_feed_fields = {
                "source_id",
                "endpoint",
                "parser_version",
                "parliament_id",
                "party_mapping",
                "unmapped_contestant_id",
                "earliest_date",
            }
            missing_feed_fields = required_feed_fields - set(feed)
            if missing_feed_fields:
                raise ValueError(
                    f"{path.name} poll feed missing fields: {sorted(missing_feed_fields)}"
                )
            if feed["source_id"] != "dawum_polls":
                raise ValueError(f"{path.name} has no implemented poll adapter")
            adapter = next(
                (
                    item
                    for item in data["source_adapters"]
                    if item["source_id"] == feed["source_id"]
                ),
                None,
            )
            if adapter is None or adapter["status"] != "approved":
                raise ValueError(f"{path.name} poll feed lacks an approved pack adapter")
            registry.require_approved(feed["source_id"])
            if feed["source_id"] not in citation_source_ids:
                raise ValueError(f"{path.name} poll feed lacks election provenance")
            targets = set(feed["party_mapping"].values()) | {feed["unmapped_contestant_id"]}
            if not targets.issubset(contestant_ids):
                raise ValueError(f"{path.name} poll mapping references unknown contestants")
        validated_feed_config(data, registry)
        data["_provenance"] = {
            "path": str(path),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        packs.append(data)
    context.add_output_metadata(
        {
            "pack_count": len(packs),
            "approved_adapter_count": approved_adapters,
            "blocked_adapter_count": blocked_adapters,
        }
    )
    return packs


@asset(group_name="catalog")
def public_catalog(jurisdiction_packs: list[dict]) -> list[dict]:
    return [
        {
            "jurisdiction": pack["jurisdiction"],
            "election": pack["election"],
            "provenance": pack["_provenance"],
        }
        for pack in jurisdiction_packs
    ]


@asset(group_name="sources", compute_kind="World Bank Indicators API")
def macro_observations(
    context: AssetExecutionContext,
    jurisdiction_packs: list[dict],
    source_policy: dict,
) -> dict[str, list[dict]]:
    countries = sorted(
        {
            pack["jurisdiction"]["iso3"]
            for pack in jurisdiction_packs
            if pack["jurisdiction"].get("iso3")
        }
    )
    current_year = datetime.now(UTC).year
    batch = WorldBankAdapter(_fetcher()).fetch_indicators(
        countries,
        [
            "FP.CPI.TOTL.ZG",
            "NY.GDP.MKTP.KD.ZG",
            "PA.NUS.FCRF",
            "SL.UEM.TOTL.ZS",
            "GC.DOD.TOTL.GD.ZS",
        ],
        current_year - 3,
        current_year,
    )
    eurostat = EurostatAdapter(_fetcher()).fetch_unemployment(
        {
            pack["jurisdiction"]["id"]: "DE"
            for pack in jurisdiction_packs
            if pack["jurisdiction"].get("iso3") == "DEU"
        },
        current_year - 3,
    )
    oecd = OecdAdapter(_fetcher()).fetch_annual_cpi(
        {
            pack["jurisdiction"]["id"]: pack["jurisdiction"]["iso3"]
            for pack in jurisdiction_packs
            if len(pack["jurisdiction"].get("iso3", "")) == 3
        },
        current_year - 3,
    )
    snapshots = (*batch.snapshots, *eurostat.snapshots, *oecd.snapshots)
    observations = (*batch.observations, *eurostat.observations, *oecd.observations)
    context.add_output_metadata(
        {
            "observation_count": len(observations),
            "snapshot_count": len(snapshots),
            "country_count": len(countries),
            "eurostat_observation_count": len(eurostat.observations),
            "oecd_observation_count": len(oecd.observations),
        }
    )
    return {
        "snapshots": [snapshot.model_dump(mode="json") for snapshot in snapshots],
        "observations": [observation.model_dump(mode="json") for observation in observations],
    }


@asset(group_name="storage", compute_kind="PostgreSQL/PostGIS")
def persisted_canonical_data(
    context: AssetExecutionContext,
    jurisdiction_packs: list[dict],
    macro_observations: dict[str, list[dict]],
) -> dict:
    dsn = database_dsn_from_env()
    if dsn is None:
        context.log.warning("PostgreSQL is not configured; canonical persistence is disabled")
        return {"status": "disabled"}
    counts = persist_canonical_batch(
        dsn, jurisdiction_packs, macro_observations, SourceRegistry.from_path()
    )
    context.add_output_metadata(counts)
    return {"status": "persisted", **counts}


@asset(group_name="calendar", compute_kind="official election-authority sources")
def official_calendar_revisions(
    context: AssetExecutionContext,
    jurisdiction_packs: list[dict],
    persisted_canonical_data: dict,
) -> dict:
    dsn = database_dsn_from_env()
    if dsn is None or persisted_canonical_data["status"] != "persisted":
        context.log.warning("PostgreSQL is not configured; calendar verification is disabled")
        return {"status": "disabled", "events": []}
    registry = SourceRegistry.from_path()
    checkpoints = PostgresCheckpointStore(dsn)
    adapter = OfficialCalendarAdapter(_fetcher(), checkpoints)
    events = []
    verified = 0
    inserted = 0
    fallbacks = 0
    for pack in jurisdiction_packs:
        election = pack["election"]
        for feed in pack.get("calendar_feeds", []):
            config = OfficialCalendarConfig.model_validate({**feed, "election_id": election["id"]})
            batch = adapter.fetch(config, save_checkpoint=False)
            if batch.fallback_used:
                fallbacks += 1
                continue
            result = persist_calendar_batch(dsn, batch, registry)
            checkpoints.save(
                AdapterCheckpoint(
                    adapter_id=f"official_calendar:{config.source_id}",
                    scope_id=config.election_id,
                    parser_version=config.parser_version,
                    source_snapshot_sha256=batch.source_snapshot.sha256,
                    payload=batch.model_dump(mode="json"),
                )
            )
            verified += 1
            inserted += int(result["inserted"])
            if result["inserted"]:
                provenance = [
                    item for item in election["sources"] if item["source_id"] == config.source_id
                ]
                event = {
                    "id": f"calendar-{config.election_id}-{result['source_revision_id']}",
                    "type": "calendar_change",
                    "election_id": config.election_id,
                    "election_date": config.election_date.isoformat(),
                    "as_of": config.available_at.isoformat(),
                    "published_at": batch.source_snapshot.retrieved_at.isoformat(),
                    "model_version": f"official-calendar:{config.parser_version}",
                    "data_quality": "A",
                    "freshness": "official calendar verified",
                    "provenance": provenance,
                    "source_revision_id": result["source_revision_id"],
                }
                _validate_live_event(event)
                events.append(event)
    context.add_output_metadata(
        {
            "verified_feed_count": verified,
            "inserted_revision_count": inserted,
            "fallback_count": fallbacks,
            "event_count": len(events),
        }
    )
    return {"status": "persisted", "events": events}


@asset(group_name="polls", compute_kind="licensed dawum JSON API")
def licensed_poll_batches(
    context: AssetExecutionContext,
    jurisdiction_packs: list[dict],
    source_policy: dict,
) -> list[DawumPollBatch]:
    if database_dsn_from_env() is None:
        context.log.warning("PostgreSQL is not configured; poll ingestion is disabled")
        return []
    if "dawum_polls" not in source_policy["approved"]:
        raise PermissionError("dawum poll ingestion is blocked by source policy")
    adapter = DawumAdapter(_fetcher())
    batches = []
    for pack in jurisdiction_packs:
        for feed in pack.get("poll_feeds", []):
            batches.append(
                adapter.fetch(
                    election_id=pack["election"]["id"],
                    endpoint=feed["endpoint"],
                    parliament_id=str(feed["parliament_id"]),
                    party_mapping={str(key): value for key, value in feed["party_mapping"].items()},
                    unmapped_contestant_id=feed["unmapped_contestant_id"],
                    parser_version=feed["parser_version"],
                    earliest_date=datetime.fromisoformat(feed["earliest_date"]).date(),
                )
            )
    context.add_output_metadata(
        {
            "batch_count": len(batches),
            "poll_count": sum(len(batch.polls) for batch in batches),
            "minimum_parser_confidence": min(
                (batch.parser_confidence for batch in batches), default=1
            ),
        }
    )
    return batches


@asset(group_name="storage", compute_kind="PostgreSQL append-only poll revisions")
def persisted_poll_data(
    context: AssetExecutionContext,
    licensed_poll_batches: list[DawumPollBatch],
    persisted_canonical_data: dict,
) -> dict:
    dsn = database_dsn_from_env()
    if dsn is None or persisted_canonical_data["status"] != "persisted":
        context.log.warning("Poll persistence withheld without canonical PostgreSQL storage")
        return {"status": "disabled", "source_revision_ids": []}
    counts = persist_poll_batches(dsn, licensed_poll_batches, SourceRegistry.from_path())
    context.add_output_metadata(
        {key: value for key, value in counts.items() if key != "source_revision_ids"}
    )
    return {"status": "persisted", **counts}


@asset(group_name="features", compute_kind="source-vintage PostgreSQL query")
def source_vintage_feature_snapshots(
    context: AssetExecutionContext,
    jurisdiction_packs: list[dict],
    persisted_canonical_data: dict,
    persisted_poll_data: dict,
) -> list[dict]:
    dsn = database_dsn_from_env()
    if (
        dsn is None
        or persisted_canonical_data["status"] == "disabled"
        or persisted_poll_data["status"] == "disabled"
    ):
        context.log.warning("PostgreSQL is not configured; source-vintage features are disabled")
        return []
    snapshots = []
    as_of = datetime.now(UTC).replace(second=0, microsecond=0)
    for pack in jurisdiction_packs:
        if not pack["jurisdiction"].get("forecast_enabled", True):
            continue
        snapshots.append(
            build_database_feature_snapshot(
                dsn,
                pack["election"]["id"],
                pack["jurisdiction"]["id"],
                as_of,
            )
        )
    inserted = persist_source_vintage_features(dsn, snapshots)
    context.add_output_metadata(
        {
            "snapshot_count": len(snapshots),
            "inserted_count": inserted,
            "complete_count": sum(
                not snapshot["values"]["missing_features"] for snapshot in snapshots
            ),
            "revision_count": sum(len(snapshot["source_revision_ids"]) for snapshot in snapshots),
        }
    )
    return snapshots


@asset(group_name="catalog", compute_kind="V-Dem official GitHub release")
def vdem_eligible_jurisdictions(context: AssetExecutionContext, source_policy: dict) -> list[dict]:
    catalog = VDemAdapter(_fetcher()).fetch_latest_catalog()
    context.add_output_metadata(
        {
            "version": catalog.version,
            "latest_year": catalog.jurisdictions[0].year if catalog.jurisdictions else None,
            "jurisdiction_count": len(catalog.jurisdictions),
            "snapshot_sha256": catalog.snapshot.sha256,
        }
    )
    return [jurisdiction.__dict__ for jurisdiction in catalog.jurisdictions]


@asset(group_name="events", compute_kind="licensed event adapter")
def security_event_observations(context: AssetExecutionContext, source_policy: dict) -> list[dict]:
    if "RetiredEvent_events" not in source_policy["approved"]:
        context.add_output_metadata(
            {
                "status": "blocked_by_source_policy",
                "observation_count": 0,
                "source_id": "RetiredEvent_events",
            }
        )
        return []
    snapshot, aggregates = RetiredEventAdapter(_fetcher()).fetch_latest_event_file()
    context.add_output_metadata(
        {
            "status": "ingested",
            "observation_count": len(aggregates),
            "snapshot_sha256": snapshot.sha256,
        }
    )
    return [aggregate.__dict__ for aggregate in aggregates]


@asset(group_name="models")
def forecast_run_manifest(
    jurisdiction_packs: list[dict],
    macro_observations: dict[str, list[dict]],
    persisted_canonical_data: dict,
    persisted_poll_data: dict,
    source_vintage_feature_snapshots: list[dict],
) -> list[dict]:
    evidence = {snapshot["election_id"]: snapshot for snapshot in source_vintage_feature_snapshots}
    return [
        {
            "election_id": pack["election"]["id"],
            "simulation_count": 1_000_000,
            "challengers": ["gaussian_monte_carlo", "markov_momentum"],
            "publication_gate": "walk_forward_champion_or_validated_baseline",
            "input_observation_count": len(macro_observations["observations"]),
            "canonical_storage_status": persisted_canonical_data["status"],
            "poll_storage_status": persisted_poll_data["status"],
            "poll_revision_ids": persisted_poll_data.get("source_revision_ids", []),
            "feature_evidence": evidence.get(pack["election"]["id"]),
        }
        for pack in jurisdiction_packs
        if pack["jurisdiction"].get("forecast_enabled", True)
    ]


def _validate_forecast_payload(
    payload: dict,
    comparison: dict,
    feature_evidence: dict | None = None,
) -> None:
    required = {
        "id",
        "election_id",
        "as_of",
        "published_at",
        "model_version",
        "model_family",
        "selection_status",
        "simulation_count",
        "seed",
        "data_quality",
        "freshness",
        "missing_drivers",
        "regional_forecast_supported",
        "input_revision_ids",
        "input_provenance",
        "outcomes",
        "coalition_outcomes",
        "provenance",
    }
    missing = required - payload.keys()
    if missing:
        raise ValueError(f"Forecast contract missing fields: {sorted(missing)}")
    if payload["simulation_count"] != 1_000_000:
        raise ValueError("Published forecasts require exactly 1,000,000 simulations")
    if not payload["provenance"]:
        raise ValueError("Forecast provenance cannot be empty")
    for revision_id in payload["input_revision_ids"]:
        uuid.UUID(revision_id)
    if payload["data_quality"] != "D" and (
        not payload["input_revision_ids"] or not payload["input_provenance"]
    ):
        raise ValueError("Quality A-C forecasts require exact source revisions and provenance")
    if bool(payload["input_revision_ids"]) != bool(payload["input_provenance"]):
        raise ValueError("Input revisions and input provenance must be declared together")
    if payload["data_quality"] != "D" and feature_evidence is not None:
        if feature_evidence["values"]["missing_features"]:
            raise ValueError("Quality A-C forecast requires complete source-vintage macro features")
        expected_revisions = set(feature_evidence["source_revision_ids"])
        if not expected_revisions.issubset(payload["input_revision_ids"]):
            raise ValueError("Forecast omits canonical source-vintage feature revisions")
        expected_sources = {item["source_id"] for item in feature_evidence["values"]["provenance"]}
        declared_sources = {item["source_id"] for item in payload["input_provenance"]}
        if not expected_sources.issubset(declared_sources):
            raise ValueError("Forecast provenance omits canonical feature sources")
    win_total = sum(item["win_probability"] for item in payload["outcomes"])
    share_total = sum(item["projected_share"] for item in payload["outcomes"])
    if abs(win_total - 1) > 1e-6 or abs(share_total - 1) > 1e-3:
        raise ValueError("Forecast probabilities are not normalized")
    winner = comparison.get("winner")
    if winner is None and payload["model_family"] != "baseline_ensemble":
        raise ValueError("An unpromoted challenger cannot be published as primary")
    if winner is not None:
        if payload["model_family"] != winner:
            raise ValueError("Published model does not match the backtest champion")
        if (
            comparison.get("simulation_count_per_model_fold") != 1_000_000
            or comparison.get("fold_count", 0) < 8
            or comparison.get("held_out_election_count", 0) < 3
            or not comparison.get("vintage_verified")
            or not comparison.get("dataset_sha256")
        ):
            raise ValueError("Backtest champion lacks production-grade evidence")


@asset(group_name="models", compute_kind="FastAPI validation boundary")
def validated_forecasts(
    context: AssetExecutionContext, forecast_run_manifest: list[dict]
) -> list[dict]:
    if not INTERNAL_TOKEN:
        raise RuntimeError("ELEXION_INTERNAL_TOKEN is required for candidate generation")
    validated = []
    headers = {"X-Elexion-Internal-Token": INTERNAL_TOKEN}
    with httpx.Client(timeout=httpx.Timeout(60, connect=10)) as client:
        for item in forecast_run_manifest:
            election_id = item["election_id"]
            comparison_response = client.get(
                f"{API_INTERNAL_URL}/v1/elections/{election_id}/model-comparison"
            )
            comparison_response.raise_for_status()
            comparison = comparison_response.json()
            selected_family = comparison.get("winner") or "baseline_ensemble"
            forecast_response = client.get(
                f"{API_INTERNAL_URL}/v1/internal/elections/{election_id}/forecast-candidate",
                params={"model_family": selected_family},
                headers=headers,
            )
            forecast_response.raise_for_status()
            payload = forecast_response.json()
            _validate_forecast_payload(payload, comparison, item["feature_evidence"])
            alternatives = {}
            for family in item["challengers"]:
                response = client.get(
                    f"{API_INTERNAL_URL}/v1/internal/elections/{election_id}/forecast-candidate",
                    params={"model_family": family},
                    headers=headers,
                )
                response.raise_for_status()
                alternative = response.json()
                if alternative["simulation_count"] != 1_000_000:
                    raise ValueError(f"{family} simulation count is invalid")
                alternatives[family] = alternative["id"]
            comparison["source_vintage_features"] = item["feature_evidence"]
            validated.append(
                {"forecast": payload, "comparison": comparison, "alternatives": alternatives}
            )
    context.add_output_metadata({"validated_forecast_count": len(validated)})
    return validated


@asset(group_name="publication", compute_kind="PostgreSQL append-only records")
def persisted_forecast_records(
    context: AssetExecutionContext,
    validated_forecasts: list[dict],
    persisted_canonical_data: dict,
) -> dict:
    dsn = database_dsn_from_env()
    if dsn is None or persisted_canonical_data["status"] == "disabled":
        context.log.warning("PostgreSQL is not configured; forecast persistence is disabled")
        return {"status": "disabled"}
    counts = persist_forecast_bundles(dsn, validated_forecasts)
    context.add_output_metadata(counts)
    return {"status": "persisted", **counts}


def _publication_is_durable(persistence_result: dict) -> bool:
    return persistence_result.get("status") == "persisted"


@asset(group_name="publication", compute_kind="immutable object storage")
def published_forecast_snapshots(
    context: AssetExecutionContext,
    validated_forecasts: list[dict],
    persisted_forecast_records: dict,
) -> list[dict]:
    if not _publication_is_durable(persisted_forecast_records):
        context.log.error(
            "Forecast publication withheld because append-only PostgreSQL persistence failed"
        )
        context.add_output_metadata({"published_snapshot_count": 0, "status": "fail_closed"})
        return []
    store = object_store_from_env(RAW_ROOT)
    publications = []
    for bundle in validated_forecasts:
        forecast = bundle["forecast"]
        content = json.dumps(forecast, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(content).hexdigest()
        key = f"published/forecasts/{forecast['election_id']}/{forecast['id']}/{digest}.json"
        uri = store.put_if_absent(
            key,
            content,
            {
                "election-id": forecast["election_id"],
                "snapshot-id": forecast["id"],
                "sha256": digest,
                "model-version": forecast["model_version"],
            },
        )
        publications.append(
            {
                "snapshot_id": forecast["id"],
                "sha256": digest,
                "uri": uri,
                "published_at": forecast["published_at"],
                "event": {
                    "id": f"forecast-{forecast['id']}",
                    "type": "forecast_publication",
                    "snapshot_id": forecast["id"],
                    "election_id": forecast["election_id"],
                    "as_of": forecast["as_of"],
                    "published_at": forecast["published_at"],
                    "model_version": forecast["model_version"],
                    "data_quality": forecast["data_quality"],
                    "freshness": forecast["freshness"],
                    "provenance": forecast["provenance"],
                },
            }
        )
    context.add_output_metadata({"published_snapshot_count": len(publications)})
    return publications


def _validate_live_event(event: dict) -> None:
    required = {
        "id",
        "type",
        "as_of",
        "published_at",
        "model_version",
        "data_quality",
        "freshness",
        "provenance",
    }
    missing = required - event.keys()
    if missing:
        raise ValueError(f"Live event missing fields: {sorted(missing)}")
    if event["type"] not in {
        "alert",
        "calendar_change",
        "forecast_publication",
        "official_result_update",
    }:
        raise ValueError(f"Unsupported event type: {event['type']}")
    if not event["provenance"]:
        raise ValueError("Live events require provenance")


async def _publish_nats_events(events: list[dict], server: str) -> None:
    for event in events:
        _validate_live_event(event)
    connection = await nats.connect(servers=[server], connect_timeout=5)
    try:
        for event in events:
            event_type = event["type"]
            await connection.publish(
                f"elexion.events.{event_type}",
                json.dumps(event, sort_keys=True, separators=(",", ":")).encode(),
            )
        await connection.flush(timeout=5)
    finally:
        await connection.drain()


@asset(group_name="publication", compute_kind="NATS pub/sub")
def published_live_events(
    context: AssetExecutionContext, published_forecast_snapshots: list[dict]
) -> dict:
    events = [publication["event"] for publication in published_forecast_snapshots]
    if not NATS_URL:
        context.log.warning("NATS_URL is unset; live event delivery is disabled")
        return {"status": "disabled", "event_count": 0}
    asyncio.run(_publish_nats_events(events, NATS_URL))
    context.add_output_metadata({"event_count": len(events), "subject": "elexion.events.*"})
    return {"status": "published", "event_count": len(events)}


@asset(group_name="calendar", compute_kind="NATS pub/sub")
def published_calendar_events(
    context: AssetExecutionContext,
    official_calendar_revisions: dict,
) -> dict:
    events = official_calendar_revisions["events"]
    if not events:
        return {"status": "no_updates", "event_count": 0}
    if official_calendar_revisions["status"] != "persisted":
        raise ValueError("Calendar events require durable persistence")
    if not NATS_URL:
        context.log.warning("NATS_URL is unset; calendar event delivery is disabled")
        return {"status": "disabled", "event_count": 0}
    asyncio.run(_publish_nats_events(events, NATS_URL))
    context.add_output_metadata({"event_count": len(events), "subject": "elexion.events.*"})
    return {"status": "published", "event_count": len(events)}


def _official_result_event(batch, pack: dict, parser_version: str) -> dict:
    reported_at = max(item.reported_at for item in batch.records)
    digest = hashlib.sha256(
        json.dumps(batch.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    provenance = [
        citation
        for citation in pack["election"]["sources"]
        if citation["source_id"] == batch.source_id
    ]
    event = {
        "id": f"official-results-{batch.election_id}-{digest[:20]}",
        "type": "official_result_update",
        "election_id": batch.election_id,
        "as_of": reported_at.isoformat(),
        "published_at": batch.retrieved_at.isoformat(),
        "model_version": f"official-results:{parser_version}",
        "data_quality": "A",
        "freshness": "certified" if all(item.is_certified for item in batch.records) else "live",
        "provenance": provenance,
        "reporting_fraction": max(item.reporting_fraction for item in batch.records),
        "results": [item.model_dump(mode="json") for item in batch.records],
        "source_snapshot_sha256": batch.records[0].source_snapshot_sha256,
    }
    _validate_live_event(event)
    return event


@asset(group_name="live_results", compute_kind="approved official results feed")
def official_result_updates(context: AssetExecutionContext, jurisdiction_packs: list[dict]) -> dict:
    dsn = database_dsn_from_env()
    if dsn is None:
        context.log.warning("PostgreSQL is not configured; official-result polling is disabled")
        return {"status": "disabled", "events": []}
    registry = SourceRegistry.from_path()
    now = datetime.now(UTC)
    configured_count, active = select_active_feeds(jurisdiction_packs, registry, now)
    if not active:
        context.add_output_metadata(
            {"configured_feed_count": configured_count, "active_feed_count": 0, "network_calls": 0}
        )
        return {"status": "outside_live_window", "events": []}

    checkpoints = PostgresCheckpointStore(dsn)
    adapter = OfficialResultAdapter(_fetcher(), checkpoints)
    events = []
    inserted_count = 0
    fallback_count = 0
    for pack, config in active:
        election_id = pack["election"]["id"]
        parser_config = config.parser_config(election_id)
        batch = adapter.fetch_results(
            config.source_id,
            config.endpoint,
            parser_config,
            save_checkpoint=False,
        )
        if batch.fallback_used:
            fallback_count += 1
            continue
        result = persist_official_result_batch(
            dsn,
            batch,
            registry.require_approved(config.source_id),
            config.parser_version,
        )
        inserted_count += int(result["inserted"])
        checkpoints.save(
            AdapterCheckpoint(
                adapter_id="official_results",
                scope_id=election_id,
                parser_version=config.parser_version,
                source_snapshot_sha256=batch.records[0].source_snapshot_sha256,
                payload=batch.model_dump(mode="json"),
            )
        )
        events.append(_official_result_event(batch, pack, config.parser_version))
    context.add_output_metadata(
        {
            "configured_feed_count": configured_count,
            "active_feed_count": len(active),
            "event_count": len(events),
            "inserted_result_count": inserted_count,
            "fallback_count": fallback_count,
        }
    )
    return {"status": "persisted", "events": events}


@asset(group_name="live_results", compute_kind="NATS pub/sub")
def published_official_result_events(
    context: AssetExecutionContext, official_result_updates: dict
) -> dict:
    events = official_result_updates["events"]
    if not events:
        return {"status": "no_updates", "event_count": 0}
    if official_result_updates["status"] != "persisted":
        raise ValueError("Official-result events require durable persistence")
    if not NATS_URL:
        context.log.warning("NATS_URL is unset; official-result event delivery is disabled")
        return {"status": "disabled", "event_count": 0}
    asyncio.run(_publish_nats_events(events, NATS_URL))
    context.add_output_metadata({"event_count": len(events), "subject": "elexion.events.*"})
    return {"status": "published", "event_count": len(events)}


refresh_job = define_asset_job(
    "refresh_forecasts",
    selection=AssetSelection.assets(
        source_policy,
        jurisdiction_packs,
        public_catalog,
        macro_observations,
        persisted_canonical_data,
        official_calendar_revisions,
        published_calendar_events,
        licensed_poll_batches,
        persisted_poll_data,
        source_vintage_feature_snapshots,
        forecast_run_manifest,
        validated_forecasts,
        persisted_forecast_records,
        published_forecast_snapshots,
        published_live_events,
    ),
)
eligibility_job = define_asset_job(
    "refresh_vdem_eligibility",
    selection=AssetSelection.assets(source_policy, vdem_eligible_jurisdictions),
)
event_refresh_job = define_asset_job(
    "refresh_security_events",
    selection=AssetSelection.assets(source_policy, security_event_observations),
)
official_result_refresh_job = define_asset_job(
    "refresh_official_results",
    selection=AssetSelection.assets(
        jurisdiction_packs,
        official_result_updates,
        published_official_result_events,
    ),
)


def _record_run_status(context: RunStatusSensorContext, status: str) -> None:
    dsn = database_dsn_from_env()
    if dsn is None:
        context.log.warning("PostgreSQL is not configured; pipeline run telemetry is disabled")
        return
    message = context.dagster_event.message if context.dagster_event else None
    record_pipeline_run_event(
        dsn,
        context.dagster_run.run_id,
        context.dagster_run.job_name,
        status,
        {"message": message[:2_000] if message else None},
    )


@run_status_sensor(
    run_status=DagsterRunStatus.SUCCESS,
    monitored_jobs=[refresh_job, eligibility_job, event_refresh_job, official_result_refresh_job],
    default_status=DefaultSensorStatus.RUNNING,
)
def pipeline_success_sensor(context: RunStatusSensorContext) -> None:
    _record_run_status(context, "success")


@run_status_sensor(
    run_status=DagsterRunStatus.FAILURE,
    monitored_jobs=[refresh_job, eligibility_job, event_refresh_job, official_result_refresh_job],
    default_status=DefaultSensorStatus.RUNNING,
)
def pipeline_failure_sensor(context: RunStatusSensorContext) -> None:
    _record_run_status(context, "failure")


daily_refresh = ScheduleDefinition(job=refresh_job, cron_schedule="15 2 * * *")
hourly_event_refresh = ScheduleDefinition(job=event_refresh_job, cron_schedule="5 * * * *")
monthly_eligibility_refresh = ScheduleDefinition(job=eligibility_job, cron_schedule="30 3 18 * *")
minute_official_result_refresh = ScheduleDefinition(
    job=official_result_refresh_job, cron_schedule="* * * * *"
)

defs = Definitions(
    assets=[
        source_policy,
        jurisdiction_packs,
        public_catalog,
        macro_observations,
        persisted_canonical_data,
        official_calendar_revisions,
        published_calendar_events,
        licensed_poll_batches,
        persisted_poll_data,
        source_vintage_feature_snapshots,
        vdem_eligible_jurisdictions,
        security_event_observations,
        forecast_run_manifest,
        validated_forecasts,
        persisted_forecast_records,
        published_forecast_snapshots,
        published_live_events,
        official_result_updates,
        published_official_result_events,
    ],
    jobs=[refresh_job, eligibility_job, event_refresh_job, official_result_refresh_job],
    schedules=[
        daily_refresh,
        hourly_event_refresh,
        monthly_eligibility_refresh,
        minute_official_result_refresh,
    ],
    sensors=[pipeline_success_sensor, pipeline_failure_sensor],
)
