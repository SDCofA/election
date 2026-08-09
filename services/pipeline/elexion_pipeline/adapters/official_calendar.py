from __future__ import annotations

import html
import re
from datetime import date, datetime

import httpx
from pydantic import BaseModel, Field, model_validator

from ..checkpoint import AdapterCheckpoint, CheckpointStore
from ..domain import RawSnapshot
from .http import HttpSnapshotFetcher, RetryableFetchError, SourceResponseError


class CalendarParseError(ValueError):
    pass


class OfficialCalendarConfig(BaseModel):
    source_id: str
    endpoint: str
    parser_version: str
    election_id: str
    election_date: date
    date_confidence: str
    status: str
    released_at: datetime
    available_at: datetime
    required_markers: list[str] = Field(min_length=1)
    minimum_confidence: float = Field(default=1, ge=0.98, le=1)

    @model_validator(mode="after")
    def validate_chronology(self) -> OfficialCalendarConfig:
        if self.released_at.tzinfo is None or self.available_at.tzinfo is None:
            raise ValueError("Calendar evidence timestamps require timezones")
        if self.released_at > self.available_at:
            raise ValueError("Calendar evidence availability predates release")
        return self


class OfficialCalendarBatch(BaseModel):
    election_id: str
    election_date: date
    date_confidence: str
    status: str
    released_at: datetime
    available_at: datetime
    parser_version: str
    parser_confidence: float = Field(ge=0, le=1)
    source_snapshot: RawSnapshot
    fallback_used: bool = False
    freshness_warning: str | None = None


def _visible_text(content: bytes) -> str:
    decoded = content.decode("utf-8", errors="replace")
    without_markup = re.sub(r"<[^>]+>", " ", decoded)
    return " ".join(html.unescape(without_markup).casefold().split())


def parse_official_calendar(
    content: bytes,
    snapshot: RawSnapshot,
    config: OfficialCalendarConfig,
) -> OfficialCalendarBatch:
    text = _visible_text(content)
    found = sum(" ".join(marker.casefold().split()) in text for marker in config.required_markers)
    confidence = found / len(config.required_markers)
    if confidence < config.minimum_confidence:
        raise CalendarParseError(
            f"Official calendar parser confidence {confidence:.3f} is below "
            f"{config.minimum_confidence:.3f}"
        )
    return OfficialCalendarBatch(
        election_id=config.election_id,
        election_date=config.election_date,
        date_confidence=config.date_confidence,
        status=config.status,
        released_at=config.released_at,
        available_at=config.available_at,
        parser_version=config.parser_version,
        parser_confidence=confidence,
        source_snapshot=snapshot,
    )


class OfficialCalendarAdapter:
    def __init__(self, fetcher: HttpSnapshotFetcher, checkpoints: CheckpointStore) -> None:
        self.fetcher = fetcher
        self.checkpoints = checkpoints

    @staticmethod
    def _adapter_id(source_id: str) -> str:
        return f"official_calendar:{source_id}"

    def fetch(
        self,
        config: OfficialCalendarConfig,
        *,
        save_checkpoint: bool = True,
    ) -> OfficialCalendarBatch:
        try:
            fetched = self.fetcher.fetch(config.source_id, config.endpoint)
            if fetched is None:
                return self._fallback(
                    config,
                    "Source returned not-modified",
                    "not_modified",
                    record_failure=False,
                )
            batch = parse_official_calendar(fetched.content, fetched.snapshot, config)
        except (httpx.TransportError, RetryableFetchError, SourceResponseError) as error:
            return self._fallback(config, str(error), "source_unavailable")
        except (CalendarParseError, UnicodeError) as error:
            return self._fallback(config, str(error), "parser_drift")
        if save_checkpoint:
            self.checkpoints.save(
                AdapterCheckpoint(
                    adapter_id=self._adapter_id(config.source_id),
                    scope_id=config.election_id,
                    parser_version=config.parser_version,
                    source_snapshot_sha256=batch.source_snapshot.sha256,
                    payload=batch.model_dump(mode="json"),
                )
            )
        return batch

    def _fallback(
        self,
        config: OfficialCalendarConfig,
        warning: str,
        failure_kind: str,
        *,
        record_failure: bool = True,
    ) -> OfficialCalendarBatch:
        adapter_id = self._adapter_id(config.source_id)
        if record_failure:
            self.checkpoints.record_failure(adapter_id, config.election_id, failure_kind, warning)
        checkpoint = self.checkpoints.load(adapter_id, config.election_id)
        if checkpoint is None:
            raise CalendarParseError(
                f"Calendar parse failed and no last-known-good exists: {warning}"
            )
        return OfficialCalendarBatch.model_validate(checkpoint.payload).model_copy(
            update={"fallback_used": True, "freshness_warning": warning}
        )
