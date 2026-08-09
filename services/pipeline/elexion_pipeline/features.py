from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import psycopg
from psycopg.rows import dict_row


@dataclass(frozen=True)
class FeatureSpec:
    key: str
    metrics: tuple[str, ...]


@dataclass(frozen=True)
class FeatureObservation:
    metric: str
    value: float
    unit: str
    observed_at: datetime
    released_at: datetime
    available_at: datetime
    revision: int
    source_revision_id: str
    source_key: str
    source_url: str
    license: str


MACRO_FEATURE_SPECS = (
    FeatureSpec("inflation", ("oecd:cpi:annual_growth", "world_bank:FP.CPI.TOTL.ZG")),
    FeatureSpec("real_gdp_growth", ("world_bank:NY.GDP.MKTP.KD.ZG",)),
    FeatureSpec(
        "unemployment",
        ("eurostat:UNE_RT_A:unemployment_rate", "world_bank:SL.UEM.TOTL.ZS"),
    ),
    FeatureSpec("government_debt", ("world_bank:GC.DOD.TOTL.GD.ZS",)),
    FeatureSpec("exchange_rate", ("world_bank:PA.NUS.FCRF",)),
)


def _encoded_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_feature_snapshot(
    election_id: str,
    jurisdiction_id: str,
    as_of: datetime,
    observations: Iterable[FeatureObservation],
    specs: tuple[FeatureSpec, ...] = MACRO_FEATURE_SPECS,
) -> dict:
    eligible = [
        item for item in observations if item.available_at <= as_of and item.observed_at <= as_of
    ]
    selected: dict[str, FeatureObservation] = {}
    for spec in specs:
        candidates = [item for item in eligible if item.metric in spec.metrics]
        if candidates:
            selected[spec.key] = max(
                candidates,
                key=lambda item: (item.available_at, item.observed_at, item.revision, item.metric),
            )

    features = {
        key: {
            "metric": item.metric,
            "value": item.value,
            "unit": item.unit,
            "observed_at": item.observed_at.isoformat(),
            "released_at": item.released_at.isoformat(),
            "available_at": item.available_at.isoformat(),
            "revision": item.revision,
            "source_revision_id": item.source_revision_id,
        }
        for key, item in sorted(selected.items())
    }
    revision_ids = sorted({item.source_revision_id for item in selected.values()})
    for revision_id in revision_ids:
        UUID(revision_id)
    provenance = [
        {
            "source_id": item.source_key,
            "url": item.source_url,
            "license": item.license,
            "source_revision_id": item.source_revision_id,
        }
        for item in sorted(
            {item.source_revision_id: item for item in selected.values()}.values(),
            key=lambda value: value.source_revision_id,
        )
    ]
    missing = sorted(spec.key for spec in specs if spec.key not in selected)
    values = {
        "features": features,
        "missing_features": missing,
        "provenance": provenance,
        "completeness": len(features) / len(specs),
        "scope": "macro_fundamentals",
    }
    return {
        "election_id": election_id,
        "jurisdiction_id": jurisdiction_id,
        "as_of": as_of.isoformat(),
        "schema_version": "canonical-macro-v1",
        "values": values,
        "source_revision_ids": revision_ids,
        "content_sha256": _encoded_hash(values),
    }


def load_feature_observations(
    dsn: str,
    jurisdiction_id: str,
    as_of: datetime,
    specs: tuple[FeatureSpec, ...] = MACRO_FEATURE_SPECS,
) -> list[FeatureObservation]:
    metrics = sorted({metric for spec in specs for metric in spec.metrics})
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        rows = connection.execute(
            """
            SELECT
              o.metric, o.value, o.unit, o.observed_at, o.released_at, o.available_at,
              o.revision, o.source_revision_id, s.source_key, s.url AS source_url,
              s.license
            FROM observations o
            JOIN source_revisions revision ON revision.id = o.source_revision_id
            JOIN sources s ON s.id = revision.source_id
            WHERE o.jurisdiction_id = %s
              AND o.available_at <= %s
              AND o.observed_at <= %s
              AND s.retrieved_at <= %s
              AND o.metric = ANY(%s)
            """,
            (jurisdiction_id, as_of, as_of, as_of, metrics),
        ).fetchall()
    return [
        FeatureObservation(
            metric=row["metric"],
            value=row["value"],
            unit=row["unit"],
            observed_at=row["observed_at"],
            released_at=row["released_at"],
            available_at=row["available_at"],
            revision=row["revision"],
            source_revision_id=str(row["source_revision_id"]),
            source_key=row["source_key"],
            source_url=row["source_url"],
            license=row["license"],
        )
        for row in rows
    ]


def build_database_feature_snapshot(
    dsn: str,
    election_id: str,
    jurisdiction_id: str,
    as_of: datetime,
) -> dict:
    return build_feature_snapshot(
        election_id,
        jurisdiction_id,
        as_of,
        load_feature_observations(dsn, jurisdiction_id, as_of),
    )
