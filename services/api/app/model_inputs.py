from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from .polling import PollAggregate, PollObservation, aggregate_polls


class ModelEvidenceStoreUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelEvidence:
    election_id: str
    as_of: datetime
    macro_features: dict[str, dict]
    missing_macro_features: tuple[str, ...]
    poll_aggregate: PollAggregate | None
    source_revision_ids: tuple[str, ...]
    provenance: tuple[dict, ...]
    content_sha256: str


def _content_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def load_model_evidence(
    dsn: str,
    election_id: str,
    contestant_ids: list[str],
) -> ModelEvidence | None:
    try:
        with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=2) as connection:
            feature = connection.execute(
                """
                SELECT as_of, values, source_revision_ids, content_sha256
                FROM feature_snapshots
                WHERE election_id = %s AND schema_version = 'canonical-macro-v1'
                ORDER BY as_of DESC LIMIT 1
                """,
                (election_id,),
            ).fetchone()
            if feature is None:
                return None
            poll_rows = connection.execute(
                """
                WITH latest AS (
                  SELECT DISTINCT ON (poll_key)
                    id, poll_key, pollster, fieldwork_end, available_at, sample_size, mode
                  FROM polls
                  JOIN sources source ON source.id = polls.source_id
                  WHERE election_id = %s
                    AND available_at <= %s
                    AND fieldwork_end <= %s
                    AND source.retrieved_at <= %s
                  ORDER BY poll_key, revision DESC
                )
                SELECT latest.*, result.contestant_id, result.share
                FROM latest
                JOIN poll_results result ON result.poll_id = latest.id
                ORDER BY latest.available_at, latest.poll_key, result.contestant_id
                """,
                (election_id, feature["as_of"], feature["as_of"], feature["as_of"]),
            ).fetchall()
            poll_values: dict[str, dict] = {}
            for row in poll_rows:
                poll = poll_values.setdefault(
                    str(row["id"]),
                    {
                        "poll_id": row["poll_key"],
                        "pollster": row["pollster"],
                        "fieldwork_end": row["fieldwork_end"].date(),
                        "available_at": row["available_at"],
                        "sample_size": row["sample_size"],
                        "mode": row["mode"],
                        "shares": {},
                    },
                )
                poll["shares"][row["contestant_id"]] = row["share"]
            polls = [
                PollObservation(
                    poll_id=value["poll_id"],
                    pollster=value["pollster"],
                    fieldwork_end=value["fieldwork_end"],
                    available_at=value["available_at"],
                    sample_size=value["sample_size"],
                    shares=tuple(float(value["shares"].get(item, 0)) for item in contestant_ids),
                    mode=value["mode"],
                )
                for value in poll_values.values()
            ]
            poll_aggregate = aggregate_polls(polls, feature["as_of"]) if polls else None
            revision_ids = {
                *(str(value) for value in feature["source_revision_ids"]),
                *poll_values.keys(),
            }
            provenance_rows = connection.execute(
                """
                SELECT revision.id AS revision_id, source.source_key, source.label, source.url,
                       source.authority, source.retrieved_at, source.license, source.license_url
                FROM source_revisions revision
                JOIN sources source ON source.id = revision.source_id
                WHERE revision.id = ANY(%s::uuid[])
                ORDER BY revision.id
                """,
                (sorted(revision_ids),),
            ).fetchall()
    except psycopg.Error as error:
        raise ModelEvidenceStoreUnavailable from error
    if len(provenance_rows) != len(revision_ids):
        raise ValueError("Model evidence contains unresolved source revisions")
    provenance = tuple(
        {
            "source_id": row["source_key"],
            "label": row["label"],
            "url": row["url"],
            "authority": row["authority"],
            "retrieved_at": row["retrieved_at"],
            "license": row["license"],
            "license_url": row["license_url"],
        }
        for row in provenance_rows
    )
    content = {
        "feature_content_sha256": feature["content_sha256"],
        "poll_ids": list(poll_aggregate.poll_ids) if poll_aggregate else [],
        "poll_shares": list(poll_aggregate.shares) if poll_aggregate else [],
        "source_revision_ids": sorted(revision_ids),
    }
    return ModelEvidence(
        election_id=election_id,
        as_of=feature["as_of"],
        macro_features=feature["values"]["features"],
        missing_macro_features=tuple(feature["values"]["missing_features"]),
        poll_aggregate=poll_aggregate,
        source_revision_ids=tuple(sorted(revision_ids)),
        provenance=provenance,
        content_sha256=_content_hash(content),
    )
