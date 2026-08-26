from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass

from ..domain import RawSnapshot
from .http import HttpSnapshotFetcher, SourceResponseError

SOURCE_ID = "RetiredEvent_events"


@dataclass(frozen=True)
class EventFile:
    table: str
    byte_count: int
    sha256: str
    url: str


@dataclass(frozen=True)
class SecurityEventAggregate:
    country_code: str
    event_count: int
    conflict_event_count: int
    mention_count: int
    average_goldstein_scale: float
    average_tone: float


def parse_last_update(content: bytes) -> tuple[EventFile, ...]:
    files: list[EventFile] = []
    for line in content.decode("utf-8", errors="strict").splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        byte_count_text, sha256, url = parts
        name = url.rsplit("/", 1)[-1].lower()
        if ".export.csv.zip" in name:
            table = "events"
        elif ".mentions.csv.zip" in name:
            table = "mentions"
        elif ".gkg.csv.zip" in name:
            table = "gkg"
        else:
            continue
        try:
            byte_count = int(byte_count_text)
        except ValueError as exc:
            raise SourceResponseError("Invalid event inventory byte count") from exc
        files.append(EventFile(table, byte_count, sha256, url))
    return tuple(files)


def aggregate_security_events(content: bytes) -> tuple[SecurityEventAggregate, ...]:
    totals: dict[str, dict[str, float]] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if len(members) != 1:
                raise SourceResponseError("Event archive must contain exactly one CSV")
            stream = io.TextIOWrapper(archive.open(members[0]), encoding="utf-8", newline="")
            for row in csv.reader(stream, delimiter="\t"):
                if len(row) < 54 or not row[53].strip():
                    continue
                country = row[53].strip().upper()
                bucket = totals.setdefault(
                    country,
                    {"events": 0, "conflicts": 0, "mentions": 0, "goldstein": 0, "tone": 0},
                )
                try:
                    quad_class = int(row[29] or 0)
                    goldstein = float(row[30] or 0)
                    mentions = int(row[31] or 0)
                    tone = float(row[34] or 0)
                except ValueError:
                    continue
                bucket["events"] += 1
                bucket["conflicts"] += int(quad_class >= 3)
                bucket["mentions"] += mentions
                bucket["goldstein"] += goldstein
                bucket["tone"] += tone
    except (OSError, zipfile.BadZipFile) as exc:
        raise SourceResponseError("Invalid event archive") from exc

    return tuple(
        SecurityEventAggregate(
            country_code=country,
            event_count=int(values["events"]),
            conflict_event_count=int(values["conflicts"]),
            mention_count=int(values["mentions"]),
            average_goldstein_scale=values["goldstein"] / values["events"],
            average_tone=values["tone"] / values["events"],
        )
        for country, values in sorted(totals.items())
    )


class RetiredEventAdapter:
    def __init__(self, fetcher: HttpSnapshotFetcher) -> None:
        self.fetcher = fetcher

    def fetch_latest_event_file(self) -> tuple[RawSnapshot, tuple[SecurityEventAggregate, ...]]:
        inventory = self.fetcher.fetch(SOURCE_ID, "lastupdate.txt")
        if inventory is None:
            raise RuntimeError("Event inventory unexpectedly returned not-modified")
        event_files = [
            item for item in parse_last_update(inventory.content) if item.table == "events"
        ]
        if not event_files:
            raise SourceResponseError("Event inventory contains no event export")
        result = self.fetcher.fetch(SOURCE_ID, event_files[-1].url)
        if result is None:
            raise RuntimeError("Event export unexpectedly returned not-modified")
        return result.snapshot, aggregate_security_events(result.content)
