from __future__ import annotations

import csv
import io
import zipfile
from collections import defaultdict
from dataclasses import dataclass

from ..domain import RawSnapshot
from .http import HttpSnapshotFetcher

SOURCE_ID = "gdelt_events"


@dataclass(frozen=True)
class GdeltFile:
    byte_count: int
    md5: str
    url: str
    table: str


@dataclass(frozen=True)
class SecurityAggregate:
    country_code: str
    event_count: int
    conflict_event_count: int
    mention_count: int
    average_tone: float
    average_goldstein: float


def parse_last_update(content: bytes) -> tuple[GdeltFile, ...]:
    files = []
    for line in content.decode("utf-8").splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        url = parts[2]
        table = "events" if ".export." in url else "mentions" if ".mentions." in url else "gkg"
        files.append(GdeltFile(byte_count=int(parts[0]), md5=parts[1], url=url, table=table))
    return tuple(files)


def aggregate_security_events(content: bytes) -> tuple[SecurityAggregate, ...]:
    totals: dict[str, dict[str, float]] = defaultdict(
        lambda: {"events": 0, "conflict": 0, "mentions": 0, "tone": 0, "goldstein": 0}
    )
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        members = [name for name in archive.namelist() if name.endswith(".CSV")]
        if len(members) != 1:
            raise ValueError("Expected one GDELT event CSV in archive")
        with archive.open(members[0]) as raw:
            rows = csv.reader(io.TextIOWrapper(raw, encoding="utf-8"), delimiter="\t")
            for row in rows:
                if len(row) < 61:
                    continue
                country = row[53]
                if not country:
                    continue
                quad_class = int(row[29]) if row[29] else 0
                mentions = int(row[31]) if row[31] else 0
                tone = float(row[34]) if row[34] else 0
                goldstein = float(row[30]) if row[30] else 0
                bucket = totals[country]
                bucket["events"] += 1
                bucket["conflict"] += int(quad_class in {3, 4})
                bucket["mentions"] += mentions
                bucket["tone"] += tone
                bucket["goldstein"] += goldstein

    return tuple(
        SecurityAggregate(
            country_code=country,
            event_count=int(values["events"]),
            conflict_event_count=int(values["conflict"]),
            mention_count=int(values["mentions"]),
            average_tone=values["tone"] / values["events"],
            average_goldstein=values["goldstein"] / values["events"],
        )
        for country, values in sorted(totals.items())
    )


class GdeltAdapter:
    def __init__(self, fetcher: HttpSnapshotFetcher) -> None:
        self.fetcher = fetcher

    def fetch_latest_event_file(self) -> tuple[RawSnapshot, tuple[SecurityAggregate, ...]]:
        inventory = self.fetcher.fetch(SOURCE_ID, "lastupdate.txt")
        if inventory is None:
            raise RuntimeError("GDELT inventory unexpectedly returned not-modified")
        event_files = [
            item for item in parse_last_update(inventory.content) if item.table == "events"
        ]
        if len(event_files) != 1:
            raise ValueError("Expected exactly one latest GDELT event file")
        event = self.fetcher.fetch(SOURCE_ID, event_files[0].url)
        if event is None:
            raise RuntimeError("GDELT event file unexpectedly returned not-modified")
        if len(event.content) != event_files[0].byte_count:
            raise ValueError("GDELT byte count does not match inventory")
        return event.snapshot, aggregate_security_events(event.content)
