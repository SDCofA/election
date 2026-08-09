from __future__ import annotations

import json
from dataclasses import dataclass

from ..domain import RawSnapshot
from .http import HttpSnapshotFetcher


@dataclass(frozen=True)
class BoundaryLayer:
    jurisdiction_id: str
    level: str
    boundary_type: str
    feature_count: int
    source_snapshot: RawSnapshot
    metadata_snapshot: RawSnapshot
    geojson: dict


def validate_geojson(payload: dict) -> int:
    if payload.get("type") != "FeatureCollection" or not isinstance(payload.get("features"), list):
        raise ValueError("Boundary payload must be a GeoJSON FeatureCollection")
    if not payload["features"]:
        raise ValueError("Boundary layer contains no features")
    for feature in payload["features"]:
        geometry = feature.get("geometry") or {}
        if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            raise ValueError("Boundary features require Polygon or MultiPolygon geometry")
        if not geometry.get("coordinates"):
            raise ValueError("Boundary feature contains empty coordinates")
        if not isinstance(feature.get("properties"), dict):
            raise TypeError("Boundary feature properties are required")
    return len(payload["features"])


class GeoBoundariesAdapter:
    def __init__(self, fetcher: HttpSnapshotFetcher) -> None:
        self.fetcher = fetcher

    def fetch(self, iso3: str, level: int = 1) -> BoundaryLayer:
        if len(iso3) != 3 or not iso3.isalpha() or not 0 <= level <= 5:
            raise ValueError("geoBoundaries requires ISO3 and ADM level 0-5")
        metadata_result = self.fetcher.fetch("geoboundaries", f"{iso3.upper()}/ADM{level}/")
        if metadata_result is None:
            raise ValueError(
                "Boundary metadata returned not-modified without cached canonical data"
            )
        metadata = json.loads(metadata_result.content)
        if isinstance(metadata, list):
            if len(metadata) != 1:
                raise ValueError("Expected one geoBoundaries metadata record")
            metadata = metadata[0]
        download_url = metadata.get("gjDownloadURL")
        if not download_url:
            raise ValueError("geoBoundaries metadata lacks gjDownloadURL")
        boundary_result = self.fetcher.fetch("geoboundaries", download_url)
        if boundary_result is None:
            raise ValueError("Boundary layer returned not-modified without cached canonical data")
        payload = json.loads(boundary_result.content)
        feature_count = validate_geojson(payload)
        return BoundaryLayer(
            jurisdiction_id=iso3.lower(),
            level=f"ADM{level}",
            boundary_type=str(metadata.get("boundaryType", "administrative")),
            feature_count=feature_count,
            source_snapshot=boundary_result.snapshot,
            metadata_snapshot=metadata_result.snapshot,
            geojson=payload,
        )
