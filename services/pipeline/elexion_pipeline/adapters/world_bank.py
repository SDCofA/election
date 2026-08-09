from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from ..domain import CanonicalObservation, RawSnapshot
from .http import HttpSnapshotFetcher, SourceResponseError

SOURCE_ID = "world_bank_wdi"


@dataclass(frozen=True)
class WorldBankBatch:
    snapshots: tuple[RawSnapshot, ...]
    observations: tuple[CanonicalObservation, ...]


@dataclass(frozen=True)
class WorldBankCountry:
    iso3: str
    iso2: str
    name: str
    region: str


class WorldBankAdapter:
    def __init__(self, fetcher: HttpSnapshotFetcher) -> None:
        self.fetcher = fetcher

    def fetch_indicators(
        self,
        countries: list[str],
        indicators: list[str],
        start_year: int,
        end_year: int,
    ) -> WorldBankBatch:
        if not countries or not indicators:
            raise ValueError("Countries and indicators are required")
        if len(indicators) > 60:
            raise ValueError("World Bank API accepts at most 60 indicators")
        if start_year > end_year:
            raise ValueError("start_year must not exceed end_year")

        endpoint = f"country/{';'.join(countries)}/indicator/{';'.join(indicators)}"
        params: dict[str, str | int] = {
            "format": "json",
            "source": 2,
            "date": f"{start_year}:{end_year}",
            "per_page": 20000,
            "page": 1,
        }
        snapshots: list[RawSnapshot] = []
        observations: list[CanonicalObservation] = []
        pages = 1
        page = 1

        while page <= pages:
            params["page"] = page
            result = self.fetcher.fetch(SOURCE_ID, endpoint, params=params)
            if result is None:
                break
            snapshots.append(result.snapshot)
            payload = json.loads(result.content)
            if not isinstance(payload, list) or len(payload) != 2:
                raise SourceResponseError("Unexpected World Bank response envelope")
            metadata, rows = payload
            pages = int(metadata.get("pages", 1))
            for row in rows or []:
                value = row.get("value")
                iso3 = row.get("countryiso3code")
                year = row.get("date")
                indicator = row.get("indicator", {}).get("id")
                if value is None or not iso3 or not indicator or not str(year).isdigit():
                    continue
                observed_at = datetime(int(year), 12, 31, tzinfo=UTC)
                observations.append(
                    CanonicalObservation(
                        jurisdiction_id=str(iso3).lower(),
                        metric=f"world_bank:{indicator}",
                        observed_at=observed_at,
                        released_at=result.snapshot.retrieved_at,
                        available_at=result.snapshot.retrieved_at,
                        value=float(value),
                        unit="source-defined",
                        source_id=SOURCE_ID,
                        source_snapshot_sha256=result.snapshot.sha256,
                        dimensions={
                            "country_name": row.get("country", {}).get("value"),
                            "indicator_name": row.get("indicator", {}).get("value"),
                            "decimal": row.get("decimal"),
                            "source_page": page,
                            "vintage_limit": "retrieval-time-only",
                        },
                    )
                )
            page += 1

        return WorldBankBatch(tuple(snapshots), tuple(observations))

    def fetch_country_catalog(self) -> tuple[RawSnapshot, tuple[WorldBankCountry, ...]]:
        result = self.fetcher.fetch(
            SOURCE_ID,
            "country",
            params={"format": "json", "per_page": 400},
        )
        if result is None:
            raise RuntimeError("World Bank country catalog unexpectedly returned not-modified")
        payload = json.loads(result.content)
        if not isinstance(payload, list) or len(payload) != 2:
            raise SourceResponseError("Unexpected World Bank country response envelope")
        countries = tuple(
            WorldBankCountry(
                iso3=str(row["id"]),
                iso2=str(row["iso2Code"]),
                name=str(row["name"]),
                region=str(row.get("region", {}).get("value") or "Global"),
            )
            for row in payload[1]
            if (row.get("id") and row.get("iso2Code") and row.get("region", {}).get("id") != "NA")
        )
        return result.snapshot, countries
