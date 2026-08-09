from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import UTC, datetime

from ..domain import CanonicalObservation, RawSnapshot
from .http import HttpSnapshotFetcher, SourceResponseError

SOURCE_ID = "eurostat_sdmx"
DATASET = "UNE_RT_A"


@dataclass(frozen=True)
class EurostatBatch:
    snapshots: tuple[RawSnapshot, ...]
    observations: tuple[CanonicalObservation, ...]


def _period_end(value: str) -> datetime:
    if len(value) == 4 and value.isdigit():
        return datetime(int(value), 12, 31, tzinfo=UTC)
    raise ValueError(f"Unsupported Eurostat period: {value}")


class EurostatAdapter:
    """Licensed SDMX-CSV adapter preserving retrieval-time vintage boundaries."""

    def __init__(self, fetcher: HttpSnapshotFetcher) -> None:
        self.fetcher = fetcher

    def fetch_unemployment(
        self,
        jurisdictions: dict[str, str],
        start_year: int,
    ) -> EurostatBatch:
        if not jurisdictions or start_year < 1900:
            raise ValueError("Eurostat jurisdictions and a valid start year are required")
        snapshots: list[RawSnapshot] = []
        observations: list[CanonicalObservation] = []
        endpoint = f"data/dataflow/ESTAT/{DATASET}/1.0/"
        for jurisdiction_id, geo in sorted(jurisdictions.items()):
            result = self.fetcher.fetch(
                SOURCE_ID,
                endpoint,
                params={
                    "c[geo]": geo,
                    "c[age]": "Y15-74",
                    "c[sex]": "T",
                    "c[unit]": "PC_ACT",
                    "c[TIME_PERIOD]": f"ge:{start_year}",
                    "format": "csvdata",
                    "formatVersion": "2.0",
                    "compress": "false",
                },
            )
            if result is None:
                continue
            snapshots.append(result.snapshot)
            rows = list(csv.DictReader(io.StringIO(result.content.decode("utf-8-sig"))))
            if not rows:
                raise SourceResponseError(f"Eurostat returned no {DATASET} observations for {geo}")
            for row in rows:
                if row.get("geo") != geo or not row.get("OBS_VALUE"):
                    continue
                observed_at = _period_end(str(row["TIME_PERIOD"]))
                observations.append(
                    CanonicalObservation(
                        jurisdiction_id=jurisdiction_id,
                        metric=f"eurostat:{DATASET}:unemployment_rate",
                        observed_at=observed_at,
                        released_at=result.snapshot.retrieved_at,
                        available_at=result.snapshot.retrieved_at,
                        value=float(row["OBS_VALUE"]),
                        unit=str(row.get("unit") or "PC_ACT"),
                        source_id=SOURCE_ID,
                        source_snapshot_sha256=result.snapshot.sha256,
                        dimensions={
                            "geo": geo,
                            "age": row.get("age"),
                            "sex": row.get("sex"),
                            "observation_flag": row.get("OBS_FLAG"),
                            "vintage_limit": "retrieval-time-only",
                        },
                    )
                )
        return EurostatBatch(tuple(snapshots), tuple(observations))
