from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pyreadr

from ..domain import RawSnapshot
from .http import HttpSnapshotFetcher, SourceResponseError

SOURCE_ID = "vdem_github"


@dataclass(frozen=True)
class EligibleJurisdiction:
    country_text_id: str
    name: str
    year: int
    regime_code: int
    regime: str


@dataclass(frozen=True)
class VDemCatalog:
    version: int
    snapshot: RawSnapshot
    jurisdictions: tuple[EligibleJurisdiction, ...]


class VDemAdapter:
    def __init__(self, fetcher: HttpSnapshotFetcher) -> None:
        self.fetcher = fetcher

    def fetch_latest_catalog(self) -> VDemCatalog:
        release = self.fetcher.fetch(SOURCE_ID, "releases/latest")
        if release is None:
            raise RuntimeError("V-Dem release metadata unexpectedly returned not-modified")
        metadata = json.loads(release.content)
        match = re.fullmatch(r"V(\d+)", metadata.get("tag_name", ""))
        if match is None:
            raise SourceResponseError("Unexpected V-Dem release tag")
        version = int(match.group(1))
        dataset_url = (
            f"https://raw.githubusercontent.com/vdeminstitute/vdemdata/V{version}/data/vdem.RData"
        )
        dataset = self.fetcher.fetch(SOURCE_ID, dataset_url)
        if dataset is None:
            raise RuntimeError("V-Dem dataset unexpectedly returned not-modified")
        jurisdictions = self._extract(dataset.content)
        return VDemCatalog(version, dataset.snapshot, jurisdictions)

    @staticmethod
    def _extract(content: bytes) -> tuple[EligibleJurisdiction, ...]:
        with tempfile.TemporaryDirectory(prefix="elexion-vdem-") as directory:
            path = Path(directory) / "vdem.RData"
            path.write_bytes(content)
            frames = pyreadr.read_r(str(path))
        if not frames:
            raise SourceResponseError("V-Dem RData contains no frames")
        frame = next(iter(frames.values()))
        required = {"year", "country_text_id", "v2x_regime"}
        missing = required - set(frame.columns)
        if missing:
            raise SourceResponseError(f"V-Dem frame missing columns: {sorted(missing)}")
        name_column = "country_name" if "country_name" in frame.columns else "country_text_id"
        latest_year = int(frame["year"].max())
        current = frame[frame["year"] == latest_year]
        current = current[current["v2x_regime"].isin([2, 3])]
        labels = {2: "electoral-democracy", 3: "liberal-democracy"}
        return tuple(
            EligibleJurisdiction(
                country_text_id=str(row["country_text_id"]),
                name=str(row[name_column]),
                year=latest_year,
                regime_code=int(row["v2x_regime"]),
                regime=labels[int(row["v2x_regime"])],
            )
            for _, row in current.sort_values(name_column).iterrows()
        )
