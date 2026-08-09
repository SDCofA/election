from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .models import ForecastSnapshot

PUBLISHED_FORECAST_QUERY = """
SELECT
  fs.id,
  fs.election_id,
  fs.as_of,
  fs.published_at,
  fs.simulation_count,
  fs.seed,
  fs.data_quality,
  fs.freshness,
  fs.headline,
  fs.majority_probability,
  fs.turnout_median,
  fs.source_manifest,
  mv.id AS model_version_id,
  mv.family AS model_family,
  sr.validation,
  features.values AS feature_values,
  COALESCE((
    SELECT jsonb_agg(jsonb_build_object(
      'contestant_id', outcome.contestant_id,
      'win_probability', outcome.win_probability,
      'projected_share', outcome.projected_share,
      'share_low', outcome.share_low,
      'share_high', outcome.share_high,
      'projected_seats', outcome.projected_seats,
      'seats_low', outcome.seats_low,
      'seats_high', outcome.seats_high
    ) ORDER BY outcome.contestant_id)
    FROM forecast_outcomes outcome
    WHERE outcome.snapshot_id = fs.id
  ), '[]'::jsonb) AS outcomes,
  COALESCE((
    SELECT jsonb_agg(jsonb_build_object(
      'member_ids', coalition.member_ids,
      'majority_probability', coalition.majority_probability,
      'seats_median', coalition.seats_median,
      'seats_low', coalition.seats_low,
      'seats_high', coalition.seats_high
    ) ORDER BY coalition.coalition_key)
    FROM forecast_coalition_outcomes coalition
    WHERE coalition.snapshot_id = fs.id
  ), '[]'::jsonb) AS coalition_outcomes
FROM forecast_snapshots fs
JOIN model_versions mv ON mv.id = fs.model_version_id
JOIN simulation_runs sr ON sr.id = fs.simulation_run_id AND sr.status = 'validated'
JOIN feature_snapshots features ON features.id = sr.feature_snapshot_id
ORDER BY fs.published_at, fs.id
"""


def snapshot_from_record(record: Mapping[str, Any]) -> ForecastSnapshot:
    manifest = dict(record["source_manifest"])
    feature_values = dict(record["feature_values"])
    validation = dict(record["validation"])
    model_version_id = str(record["model_version_id"])
    suffix = f":{record['model_family']}"
    model_version = model_version_id.removesuffix(suffix)
    return ForecastSnapshot.model_validate(
        {
            "id": record["id"],
            "election_id": record["election_id"],
            "as_of": record["as_of"],
            "published_at": record["published_at"],
            "model_version": model_version,
            "model_family": record["model_family"],
            "selection_status": validation["selection_status"],
            "simulation_count": record["simulation_count"],
            "seed": record["seed"],
            "data_quality": record["data_quality"],
            "freshness": record["freshness"],
            "missing_drivers": feature_values.get("missing_drivers", []),
            "regional_forecast_supported": validation.get("regional_forecast_supported", False),
            "headline": record["headline"],
            "majority_probability": record["majority_probability"],
            "turnout_median": record["turnout_median"],
            "outcomes": record["outcomes"],
            "coalition_outcomes": record["coalition_outcomes"],
            "drivers": feature_values.get("drivers", []),
            "methodology_url": "/methodology",
            "input_revision_ids": feature_values.get("input_revision_ids", []),
            "input_provenance": manifest.get("input_provenance", []),
            "provenance": manifest.get("provenance", []),
        }
    )


def load_published_forecasts(dsn: str) -> list[ForecastSnapshot]:
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        records = connection.execute(PUBLISHED_FORECAST_QUERY).fetchall()
    return [snapshot_from_record(record) for record in records]
