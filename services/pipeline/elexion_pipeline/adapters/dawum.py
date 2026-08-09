from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator

from ..domain import RawSnapshot
from .http import HttpSnapshotFetcher

BERLIN = ZoneInfo("Europe/Berlin")
LICENSE_ID = "ODC-ODbL-1.0"
LICENSE_URL = "https://opendatacommons.org/licenses/odbl/1-0/"


class DawumPoll(BaseModel):
    poll_key: str
    election_id: str
    pollster: str
    sponsor: str
    mode: str
    population: str = "eligible_voters"
    fieldwork_start: datetime
    fieldwork_end: datetime
    released_at: datetime
    available_at: datetime
    sample_size: int = Field(gt=0)
    shares: dict[str, float]
    raw_party_results: dict[str, float]
    date_precision: str = "day"

    @model_validator(mode="after")
    def validate_poll(self) -> DawumPoll:
        if not (
            self.fieldwork_start <= self.fieldwork_end <= self.released_at <= self.available_at
        ):
            raise ValueError("Poll source-vintage chronology is invalid")
        if not self.shares or any(value < 0 or value > 1 for value in self.shares.values()):
            raise ValueError("Poll shares must lie between zero and one")
        if abs(sum(self.shares.values()) - 1) > 0.001:
            raise ValueError("Poll shares must be normalized")
        return self


class DawumPollBatch(BaseModel):
    source_snapshot: RawSnapshot
    parser_version: str
    parser_confidence: float = Field(ge=0, le=1)
    database_updated_at: datetime
    polls: list[DawumPoll] = Field(min_length=1)


def _day_start(value: str) -> datetime:
    return datetime.combine(datetime.fromisoformat(value).date(), time.min, tzinfo=BERLIN)


def _mode(value: str) -> str:
    normalized = value.casefold()
    if "telefon" in normalized and "online" in normalized:
        return "mixed"
    if "telefon" in normalized:
        return "live_phone"
    if "online" in normalized:
        return "online"
    return "mixed"


def parse_dawum(
    content: bytes,
    snapshot: RawSnapshot,
    *,
    election_id: str,
    parliament_id: str,
    party_mapping: dict[str, str],
    unmapped_contestant_id: str,
    parser_version: str,
    earliest_date: date | None = None,
    minimum_confidence: float = 0.98,
) -> DawumPollBatch:
    payload = json.loads(content)
    license_data = payload.get("Database", {}).get("License", {})
    if license_data.get("Shortcut") != "ODC-ODbL" or license_data.get("Link") != LICENSE_URL:
        raise ValueError("dawum license contract changed")
    database_updated_at = datetime.fromisoformat(payload["Database"]["Last_Update"])
    if database_updated_at.tzinfo is None:
        raise ValueError("dawum database update requires a timezone")

    institutes = payload.get("Institutes", {})
    taskers = payload.get("Taskers", {})
    methods = payload.get("Methods", {})
    candidates = [
        (poll_id, value)
        for poll_id, value in payload.get("Surveys", {}).items()
        if str(value.get("Parliament_ID")) == parliament_id
        and (earliest_date is None or date.fromisoformat(value["Date"]) >= earliest_date)
    ]
    polls = []
    for poll_id, value in candidates:
        try:
            raw_results = {
                str(party_id): float(result) for party_id, result in value["Results"].items()
            }
            grouped: dict[str, float] = {}
            for party_id, result in raw_results.items():
                contestant_id = party_mapping.get(party_id, unmapped_contestant_id)
                grouped[contestant_id] = grouped.get(contestant_id, 0) + result
            total = sum(grouped.values())
            if total <= 0:
                raise ValueError("Poll result total must be positive")
            release_day = _day_start(value["Date"])
            released_at = release_day + timedelta(days=1) - timedelta(microseconds=1)
            available_at = release_day + timedelta(days=1)
            polls.append(
                DawumPoll(
                    poll_key=f"dawum:{poll_id}",
                    election_id=election_id,
                    pollster=institutes[str(value["Institute_ID"])]["Name"],
                    sponsor=taskers[str(value["Tasker_ID"])]["Name"],
                    mode=_mode(methods[str(value["Method_ID"])]["Name"]),
                    fieldwork_start=_day_start(value["Survey_Period"]["Date_Start"]),
                    fieldwork_end=_day_start(value["Survey_Period"]["Date_End"]),
                    released_at=released_at,
                    available_at=available_at,
                    sample_size=int(value["Surveyed_Persons"]),
                    shares={key: result / total for key, result in sorted(grouped.items())},
                    raw_party_results=raw_results,
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    if not candidates:
        raise ValueError("No dawum polls found for configured parliament")
    confidence = len(polls) / len(candidates)
    if confidence < minimum_confidence:
        raise ValueError(
            f"dawum parser confidence {confidence:.3f} is below {minimum_confidence:.3f}"
        )
    return DawumPollBatch(
        source_snapshot=snapshot,
        parser_version=parser_version,
        parser_confidence=confidence,
        database_updated_at=database_updated_at,
        polls=sorted(polls, key=lambda item: (item.available_at, item.poll_key)),
    )


class DawumAdapter:
    def __init__(self, fetcher: HttpSnapshotFetcher) -> None:
        self.fetcher = fetcher

    def fetch(
        self,
        *,
        election_id: str,
        endpoint: str,
        parliament_id: str,
        party_mapping: dict[str, str],
        unmapped_contestant_id: str,
        parser_version: str,
        earliest_date: date | None = None,
    ) -> DawumPollBatch:
        fetched = self.fetcher.fetch("dawum_polls", endpoint)
        if fetched is None:
            raise ValueError("dawum returned not-modified without a current snapshot")
        return parse_dawum(
            fetched.content,
            fetched.snapshot,
            election_id=election_id,
            parliament_id=parliament_id,
            party_mapping=party_mapping,
            unmapped_contestant_id=unmapped_contestant_id,
            parser_version=parser_version,
            earliest_date=earliest_date,
        )
