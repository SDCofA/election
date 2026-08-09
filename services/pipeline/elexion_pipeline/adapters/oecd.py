from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import UTC, datetime

from ..domain import CanonicalObservation, RawSnapshot
from .http import HttpSnapshotFetcher, SourceResponseError

SOURCE_ID = "oecd_sdmx"
DATAFLOW = "OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL,1.0"


@dataclass(frozen=True)
class OecdBatch:
    snapshots: tuple[RawSnapshot, ...]
    observations: tuple[CanonicalObservation, ...]


class OecdAdapter:
    """Narrow OECD-owned CPI query with one retrieval-time vintage per batch."""

    def __init__(self, fetcher: HttpSnapshotFetcher) -> None:
        self.fetcher = fetcher

    def fetch_annual_cpi(
        self,
        jurisdictions: dict[str, str],
        start_year: int,
    ) -> OecdBatch:
        if not jurisdictions or start_year < 1900:
            raise ValueError("OECD jurisdictions and a valid start year are required")
        iso3_to_jurisdiction = {
            iso3.upper(): jurisdiction for jurisdiction, iso3 in jurisdictions.items()
        }
        if len(iso3_to_jurisdiction) != len(jurisdictions):
            raise ValueError("Each OECD jurisdiction must use a unique ISO3 code")
        areas = "+".join(sorted(iso3_to_jurisdiction))
        endpoint = f"data/{DATAFLOW}/{areas}.A.N.CPI.PA._T.N.GY"
        result = self.fetcher.fetch(
            SOURCE_ID,
            endpoint,
            params={
                "startPeriod": start_year,
                "dimensionAtObservation": "AllDimensions",
                "format": "csvfile",
            },
        )
        if result is None:
            return OecdBatch((), ())
        rows = list(csv.DictReader(io.StringIO(result.content.decode("utf-8-sig"))))
        if not rows:
            raise SourceResponseError("OECD returned no annual CPI observations")
        observations = []
        for row in rows:
            iso3 = str(row.get("REF_AREA") or "").upper()
            period = str(row.get("TIME_PERIOD") or "")
            value = row.get("OBS_VALUE")
            if iso3 not in iso3_to_jurisdiction or not period.isdigit() or value in {None, ""}:
                continue
            if (
                row.get("FREQ") != "A"
                or row.get("METHODOLOGY") != "N"
                or row.get("MEASURE") != "CPI"
                or row.get("UNIT_MEASURE") != "PA"
                or row.get("EXPENDITURE") != "_T"
                or row.get("TRANSFORMATION") != "GY"
            ):
                raise SourceResponseError("OECD CPI response dimensions drifted from contract")
            observations.append(
                CanonicalObservation(
                    jurisdiction_id=iso3_to_jurisdiction[iso3],
                    metric="oecd:cpi:annual_growth",
                    observed_at=datetime(int(period), 12, 31, tzinfo=UTC),
                    released_at=result.snapshot.retrieved_at,
                    available_at=result.snapshot.retrieved_at,
                    value=float(value),
                    unit="percent_per_annum",
                    source_id=SOURCE_ID,
                    source_snapshot_sha256=result.snapshot.sha256,
                    dimensions={
                        "ref_area": iso3,
                        "dataflow": row.get("DATAFLOW"),
                        "observation_status": row.get("OBS_STATUS"),
                        "vintage_limit": "retrieval-time-only",
                    },
                )
            )
        if not observations:
            raise SourceResponseError("OECD returned no usable annual CPI observations")
        return OecdBatch((result.snapshot,), tuple(observations))
