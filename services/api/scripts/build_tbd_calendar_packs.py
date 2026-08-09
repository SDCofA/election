from __future__ import annotations

import json
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
CATALOG_PATH = APP_ROOT / "catalog" / "vdem-v16.json"
AUTHORITIES_PATH = APP_ROOT / "catalog" / "electoral-authorities-v1.json"
PACKS_ROOT = APP_ROOT / "packs"
OUTPUT_ROOT = PACKS_ROOT / "generated"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build() -> int:
    catalog = load_json(CATALOG_PATH)
    directory = load_json(AUTHORITIES_PATH)
    reviewed_at = directory["reviewed_at"]
    horizon_year = int(reviewed_at[:4]) + 3
    horizon_date = f"{horizon_year}{reviewed_at[4:10]}"
    authorities = directory["authorities"]
    existing = {load_json(path)["jurisdiction"]["id"] for path in PACKS_ROOT.glob("*.json")}
    catalog_by_id = {item["id"]: item for item in catalog["jurisdictions"]}
    unknown_authorities = sorted(set(authorities) - set(catalog_by_id))
    if unknown_authorities:
        raise ValueError(
            f"Authority directory contains unknown jurisdictions: {unknown_authorities}"
        )
    uncovered = {
        jurisdiction_id: catalog_by_id[jurisdiction_id]
        for jurisdiction_id in authorities
        if jurisdiction_id not in existing
    }

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    for jurisdiction_id, item in sorted(uncovered.items()):
        authority = authorities[jurisdiction_id]
        source_id = f"{jurisdiction_id}_electoral_authority_reference"
        payload = {
            "jurisdiction": {
                **item,
                "forecast_enabled": True,
                "coverage_status": "forecast",
                "blocking_reasons": [],
            },
            "source_adapters": [
                {
                    "source_id": source_id,
                    "status": "reference_only_no_ingestion",
                    "formats": ["html"],
                }
            ],
            "rules": {
                "engine": "unresolved",
                "validation_status": "exploratory_proxy",
                "forecast_mode": "national_control_scenario",
                "authority_url": authority["url"],
            },
            "feature_priors": {"status": "structural_proxy"},
            "coalition_constraints": [],
            "map": {
                "level": "national",
                "geometry_status": "suppressed_until_validated",
            },
            "model": {
                "base_shares": [0.40, 0.40, 0.20],
                "volatility": 0.16,
                "turnout": 0.62,
                "data_quality": "D",
                "freshness": "three-year structural scenario; official date, mechanics and ballot pending",
                "headline": "No official date or ballot yet; this is a high-uncertainty governing-versus-opposition control scenario.",
            },
            "drivers": [
                {
                    "key": "incumbency",
                    "label": "Governing-camp incumbency",
                    "value": "Structural prior only",
                    "contribution": 0.0,
                    "direction": "government",
                    "confidence": 0.20,
                },
                {
                    "key": "economy",
                    "label": "Economic voting environment",
                    "value": "Source-vintage inputs pending",
                    "contribution": 0.0,
                    "direction": "government",
                    "confidence": 0.10,
                },
                {
                    "key": "opposition_selection",
                    "label": "Opposition coordination",
                    "value": "Candidate field unresolved",
                    "contribution": 0.0,
                    "direction": "opposition",
                    "confidence": 0.10,
                },
                {
                    "key": "timing",
                    "label": "Election timing",
                    "value": "Three-year planning horizon",
                    "contribution": 0.0,
                    "direction": "neutral",
                    "confidence": 0.10,
                },
            ],
            "election": {
                "id": f"{jurisdiction_id}-next-national",
                "jurisdiction_id": jurisdiction_id,
                "name": "Next National Election",
                "election_date": horizon_date,
                "date_confidence": "three-year structural horizon; official date pending",
                "system": "unresolved",
                "status": "exploratory forecast; official date, mechanics and ballot pending",
                "last_updated": reviewed_at,
                "contestants": [
                    {
                        "id": "government-camp",
                        "name": "Governing camp / incumbent-aligned nominee",
                        "short_name": "GOV",
                        "color": "#1f6f8b",
                        "incumbent": True,
                        "ideology": "government-control scenario",
                        "ballot_status": "scenario",
                        "basis": "Structural proxy; not an official ballot entry.",
                    },
                    {
                        "id": "opposition-camp",
                        "name": "Leading opposition camp / nominee",
                        "short_name": "OPP",
                        "color": "#c43d4f",
                        "ideology": "opposition-control scenario",
                        "ballot_status": "scenario",
                        "basis": "Structural proxy; not an official ballot entry.",
                    },
                    {
                        "id": "other-field",
                        "name": "Other parties / candidates",
                        "short_name": "OTH",
                        "color": "#746b5f",
                        "ideology": "unresolved field",
                        "ballot_status": "scenario",
                        "basis": "Residual field used while nominations remain unresolved.",
                    },
                ],
                "potential_candidates": [
                    {
                        "id": "government-camp",
                        "name": "Governing camp / incumbent-aligned nominee",
                        "short_name": "GOV",
                        "color": "#1f6f8b",
                        "incumbent": True,
                        "ideology": "government-control scenario",
                        "ballot_status": "scenario",
                        "basis": "Structural proxy; replace with named contenders as sourced signals arrive.",
                    },
                    {
                        "id": "opposition-camp",
                        "name": "Leading opposition camp / nominee",
                        "short_name": "OPP",
                        "color": "#c43d4f",
                        "ideology": "opposition-control scenario",
                        "ballot_status": "scenario",
                        "basis": "Structural proxy; replace with named contenders as sourced signals arrive.",
                    },
                    {
                        "id": "other-field",
                        "name": "Other parties / candidates",
                        "short_name": "OTH",
                        "color": "#746b5f",
                        "ideology": "unresolved field",
                        "ballot_status": "scenario",
                        "basis": "Residual field; not an official ballot list.",
                    },
                ],
                "sources": [
                    {
                        "source_id": source_id,
                        "label": authority["label"],
                        "url": authority["url"],
                        "authority": "official reference",
                        "retrieved_at": reviewed_at,
                        "license": "LINK-ONLY-NO-INGESTION",
                        "license_url": authority["url"],
                    }
                ],
            },
        }
        output = OUTPUT_ROOT / f"{jurisdiction_id}.json"
        output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return len(uncovered)


if __name__ == "__main__":
    print(f"generated={build()}")
