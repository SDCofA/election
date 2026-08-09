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
    authorities = directory["authorities"]
    existing = {load_json(path)["jurisdiction"]["id"] for path in PACKS_ROOT.glob("*.json")}
    uncovered = {
        item["id"]: item for item in catalog["jurisdictions"] if item["id"] not in existing
    }
    if set(authorities) != set(uncovered):
        missing = sorted(set(uncovered) - set(authorities))
        extra = sorted(set(authorities) - set(uncovered))
        raise ValueError(f"Authority directory mismatch; missing={missing}, extra={extra}")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    for jurisdiction_id, item in sorted(uncovered.items()):
        authority = authorities[jurisdiction_id]
        source_id = f"{jurisdiction_id}_electoral_authority_reference"
        payload = {
            "jurisdiction": {
                **item,
                "forecast_enabled": False,
                "coverage_status": "mechanics_blocked",
                "blocking_reasons": [
                    "Next national election date has not been captured from an approved reusable authority release",
                    "Electoral mechanics and contestant identities remain unresolved",
                ],
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
                "validation_status": "mechanics_blocked",
                "authority_url": authority["url"],
            },
            "feature_priors": {"status": "unresolved"},
            "coalition_constraints": [],
            "map": {
                "level": "national",
                "geometry_status": "suppressed_until_validated",
            },
            "election": {
                "id": f"{jurisdiction_id}-next-national",
                "jurisdiction_id": jurisdiction_id,
                "name": "Next National Election",
                "election_date": None,
                "date_confidence": "tbd",
                "system": "unresolved",
                "status": "TBD — awaiting an approved official calendar release",
                "last_updated": reviewed_at,
                "contestants": [],
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
