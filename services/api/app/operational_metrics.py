from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row


def _label(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _base_lines(up: int) -> list[str]:
    return [
        "# HELP elexion_pipeline_telemetry_up Pipeline telemetry database query status.",
        "# TYPE elexion_pipeline_telemetry_up gauge",
        f"elexion_pipeline_telemetry_up {up}",
    ]


def operational_metric_lines(dsn: str | None) -> list[str]:
    if not dsn:
        return _base_lines(0)
    try:
        with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=2) as connection:
            pipeline = connection.execute(
                """
                SELECT job_name,
                       count(*) FILTER (WHERE status = 'failure') AS failures,
                       extract(epoch FROM max(occurred_at)
                         FILTER (WHERE status = 'success')) AS last_success
                FROM pipeline_run_events
                GROUP BY job_name
                """
            ).fetchall()
            adapters = connection.execute(
                """
                SELECT adapter_id, scope_id,
                       extract(epoch FROM max(occurred_at)
                         FILTER (WHERE status = 'success')) AS last_success
                FROM adapter_health_events
                GROUP BY adapter_id, scope_id
                """
            ).fetchall()
            adapter_failures = connection.execute(
                """
                SELECT adapter_id, scope_id, failure_kind, count(*) AS failures
                FROM adapter_health_events
                WHERE status = 'failure'
                GROUP BY adapter_id, scope_id, failure_kind
                """
            ).fetchall()
    except psycopg.Error:
        return _base_lines(0)

    lines = _base_lines(1)
    lines.extend(
        [
            "# HELP elexion_pipeline_run_failures_total Failed Dagster runs.",
            "# TYPE elexion_pipeline_run_failures_total counter",
            "# HELP elexion_pipeline_last_success_timestamp_seconds Latest successful Dagster run.",
            "# TYPE elexion_pipeline_last_success_timestamp_seconds gauge",
        ]
    )
    for row in pipeline:
        labels = f'job_name="{_label(row["job_name"])}"'
        lines.append(f"elexion_pipeline_run_failures_total{{{labels}}} {row['failures']}")
        if row["last_success"] is not None:
            lines.append(
                f"elexion_pipeline_last_success_timestamp_seconds{{{labels}}} "
                f"{float(row['last_success']):.3f}"
            )
    lines.extend(
        [
            "# HELP elexion_adapter_last_success_timestamp_seconds Latest successful adapter parse.",
            "# TYPE elexion_adapter_last_success_timestamp_seconds gauge",
            "# HELP elexion_adapter_failures_total Adapter fallback and drift failures.",
            "# TYPE elexion_adapter_failures_total counter",
        ]
    )
    for row in adapters:
        if row["last_success"] is None:
            continue
        labels = f'adapter_id="{_label(row["adapter_id"])}",scope_id="{_label(row["scope_id"])}"'
        lines.append(
            f"elexion_adapter_last_success_timestamp_seconds{{{labels}}} "
            f"{float(row['last_success']):.3f}"
        )
    for row in adapter_failures:
        labels = (
            f'adapter_id="{_label(row["adapter_id"])}",'
            f'scope_id="{_label(row["scope_id"])}",'
            f'failure_kind="{_label(row["failure_kind"])}"'
        )
        lines.append(f"elexion_adapter_failures_total{{{labels}}} {row['failures']}")
    return lines
