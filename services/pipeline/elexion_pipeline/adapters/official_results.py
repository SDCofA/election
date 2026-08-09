from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from ..checkpoint import AdapterCheckpoint, CheckpointStore
from .http import HttpSnapshotFetcher, RetryableFetchError, SourceResponseError


class ResultParseError(ValueError):
    pass


class OfficialResultRecord(BaseModel):
    election_id: str
    reporting_unit_id: str
    contestant_id: str
    votes: int = Field(ge=0)
    reporting_fraction: float = Field(ge=0, le=1)
    reported_at: datetime
    is_certified: bool = False
    source_snapshot_sha256: str


class OfficialResultBatch(BaseModel):
    election_id: str
    records: list[OfficialResultRecord] = Field(min_length=1)
    parser_confidence: float = Field(ge=0, le=1)
    source_url: str
    retrieved_at: datetime
    source_id: str
    source_snapshot_uri: str
    source_license_id: str
    source_attribution: str
    source_usage_scope: str
    source_content_type: str
    source_byte_count: int = Field(ge=0)
    fallback_used: bool = False
    freshness_warning: str | None = None


@dataclass(frozen=True)
class ResultParserConfig:
    format: Literal["json", "csv"]
    parser_version: str
    election_id: str
    unit_field: str = "reporting_unit_id"
    contestant_field: str = "contestant_id"
    votes_field: str = "votes"
    reporting_field: str = "reporting_fraction"
    reported_at_field: str = "reported_at"
    certified_field: str = "is_certified"
    json_list_field: str = "results"
    minimum_confidence: float = 0.98


def _rows(content: bytes, config: ResultParserConfig) -> list[dict]:
    if config.format == "csv":
        return list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
    payload = json.loads(content)
    if isinstance(payload, list):
        return payload
    values = payload.get(config.json_list_field)
    return values if isinstance(values, list) else []


def _as_bool(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "certified"}


def _timestamp(value) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Official result timestamp requires a timezone")
    return parsed


def parse_results(content: bytes, snapshot, config: ResultParserConfig) -> OfficialResultBatch:
    rows = _rows(content, config)
    if not rows:
        raise ResultParseError("No official result rows found")
    records = []
    for row in rows:
        try:
            records.append(
                OfficialResultRecord(
                    election_id=config.election_id,
                    reporting_unit_id=str(row[config.unit_field]).strip(),
                    contestant_id=str(row[config.contestant_field]).strip(),
                    votes=int(row[config.votes_field]),
                    reporting_fraction=float(row[config.reporting_field]),
                    reported_at=_timestamp(row[config.reported_at_field]),
                    is_certified=_as_bool(row.get(config.certified_field, False)),
                    source_snapshot_sha256=snapshot.sha256,
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    confidence = len(records) / len(rows)
    if not records:
        raise ResultParseError("No valid official result rows found")
    keys = {(item.reporting_unit_id, item.contestant_id) for item in records}
    if len(keys) != len(records):
        raise ResultParseError("Duplicate official result rows detected")
    return OfficialResultBatch(
        election_id=config.election_id,
        records=records,
        parser_confidence=confidence,
        source_url=snapshot.source_url,
        retrieved_at=snapshot.retrieved_at,
        source_id=snapshot.source_id,
        source_snapshot_uri=snapshot.object_uri,
        source_license_id=snapshot.license_id,
        source_attribution=snapshot.attribution,
        source_usage_scope=snapshot.usage_scope,
        source_content_type=snapshot.content_type,
        source_byte_count=snapshot.byte_count,
    )


def validate_monotonic_results(previous: OfficialResultBatch, current: OfficialResultBatch) -> None:
    prior = {(item.reporting_unit_id, item.contestant_id): item for item in previous.records}
    for item in current.records:
        old = prior.get((item.reporting_unit_id, item.contestant_id))
        if old is None:
            continue
        if item.votes < old.votes:
            raise ResultParseError("Official vote total decreased")
        if item.reporting_fraction < old.reporting_fraction:
            raise ResultParseError("Official reporting fraction decreased")
        if item.reported_at < old.reported_at:
            raise ResultParseError("Official result timestamp moved backwards")


class OfficialResultAdapter:
    def __init__(
        self,
        fetcher: HttpSnapshotFetcher,
        checkpoints: CheckpointStore | None = None,
    ) -> None:
        self.fetcher = fetcher
        self.checkpoints = checkpoints
        self._last_known_good: dict[str, OfficialResultBatch] = {}

    def fetch_results(
        self,
        source_id: str,
        endpoint: str,
        config: ResultParserConfig,
        *,
        save_checkpoint: bool = True,
    ) -> OfficialResultBatch:
        try:
            fetched = self.fetcher.fetch(source_id, endpoint)
        except (httpx.TransportError, RetryableFetchError, SourceResponseError) as error:
            return self._fallback(config.election_id, str(error), "source_unavailable")
        if fetched is None:
            return self._fallback(
                config.election_id,
                "Source returned not-modified",
                "source_unavailable",
            )
        try:
            batch = parse_results(fetched.content, fetched.snapshot, config)
            if batch.parser_confidence < config.minimum_confidence:
                raise ResultParseError("Official result parser confidence fell below threshold")
            previous = self._previous(config.election_id)
            if previous:
                validate_monotonic_results(previous, batch)
        except (ResultParseError, json.JSONDecodeError, UnicodeError) as error:
            warning = str(error)
            failure_kind = (
                "source_drift"
                if any(
                    marker in warning
                    for marker in ("vote total decreased", "fraction decreased", "moved backwards")
                )
                else "parser_drift"
            )
            return self._fallback(config.election_id, warning, failure_kind)
        self._last_known_good[config.election_id] = batch
        if self.checkpoints is not None and save_checkpoint:
            self.checkpoints.save(
                AdapterCheckpoint(
                    adapter_id="official_results",
                    scope_id=config.election_id,
                    parser_version=config.parser_version,
                    source_snapshot_sha256=fetched.snapshot.sha256,
                    payload=batch.model_dump(mode="json"),
                )
            )
        return batch

    def _previous(self, election_id: str) -> OfficialResultBatch | None:
        previous = self._last_known_good.get(election_id)
        if previous is None and self.checkpoints is not None:
            checkpoint = self.checkpoints.load("official_results", election_id)
            if checkpoint is not None:
                previous = OfficialResultBatch.model_validate(checkpoint.payload)
        return previous

    def _fallback(
        self,
        election_id: str,
        warning: str,
        failure_kind: str,
    ) -> OfficialResultBatch:
        if self.checkpoints is not None:
            self.checkpoints.record_failure(
                "official_results",
                election_id,
                failure_kind,
                warning,
            )
        previous = self._previous(election_id)
        if previous is None:
            raise ResultParseError(f"Result parse failed and no last-known-good exists: {warning}")
        return previous.model_copy(update={"fallback_used": True, "freshness_warning": warning})
