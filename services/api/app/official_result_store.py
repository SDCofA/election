from __future__ import annotations

import psycopg
from psycopg.rows import dict_row


class OfficialResultStoreUnavailable(RuntimeError):
    pass


def load_official_results(dsn: str, election_id: str) -> dict | None:
    try:
        with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=2) as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT ON (result.reporting_unit_id, result.contestant_id)
                  result.reporting_unit_id, unit.name AS reporting_unit_name,
                  result.contestant_id, contestant.name AS contestant_name,
                  result.votes, result.reporting_fraction, result.reported_at,
                  result.is_certified, source.source_key, source.label, source.url,
                  source.authority, source.retrieved_at, source.license,
                  source.license_url, source.parser_version, source.content_sha256
                FROM official_results result
                JOIN reporting_units unit
                  ON unit.election_id = result.election_id
                 AND unit.id = result.reporting_unit_id
                JOIN contestants contestant
                  ON contestant.election_id = result.election_id
                 AND contestant.id = result.contestant_id
                JOIN sources source ON source.id = result.source_id
                WHERE result.election_id = %s
                ORDER BY result.reporting_unit_id, result.contestant_id,
                         result.reported_at DESC
                """,
                (election_id,),
            ).fetchall()
    except psycopg.Error as error:
        raise OfficialResultStoreUnavailable from error
    if not rows:
        return None
    provenance = []
    seen_sources = set()
    for row in rows:
        source_key = (row["source_key"], row["content_sha256"])
        if source_key in seen_sources:
            continue
        seen_sources.add(source_key)
        provenance.append(
            {
                "source_id": row["source_key"],
                "label": row["label"],
                "url": row["url"],
                "authority": row["authority"],
                "retrieved_at": row["retrieved_at"],
                "license": row["license"],
                "license_url": row["license_url"],
            }
        )
    parser_versions = sorted({row["parser_version"] for row in rows})
    return {
        "election_id": election_id,
        "feed_available": True,
        "status": "certified" if all(row["is_certified"] for row in rows) else "live",
        "reporting_fraction": max(row["reporting_fraction"] for row in rows),
        "results": [
            {
                "reporting_unit_id": row["reporting_unit_id"],
                "reporting_unit_name": row["reporting_unit_name"],
                "contestant_id": row["contestant_id"],
                "contestant_name": row["contestant_name"],
                "votes": row["votes"],
                "reporting_fraction": row["reporting_fraction"],
                "reported_at": row["reported_at"],
                "is_certified": row["is_certified"],
                "source_snapshot_sha256": row["content_sha256"],
            }
            for row in rows
        ],
        "as_of": max(row["reported_at"] for row in rows),
        "published_at": max(row["retrieved_at"] for row in rows),
        "model_version": f"official-results:{'+'.join(parser_versions)}",
        "data_quality": "A",
        "freshness": "certified" if all(row["is_certified"] for row in rows) else "live",
        "provenance": provenance,
    }
