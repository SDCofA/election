from __future__ import annotations

import argparse
import json
from pathlib import Path

from elexion_pipeline.adapters.http import HttpSnapshotFetcher
from elexion_pipeline.adapters.vdem import VDemAdapter
from elexion_pipeline.adapters.world_bank import WorldBankAdapter
from elexion_pipeline.catalog import build_api_catalog
from elexion_pipeline.registry import SourceRegistry
from elexion_pipeline.storage import LocalObjectStore, SnapshotWriter


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate API jurisdiction bootstrap catalog")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--object-root", type=Path, required=True)
    args = parser.parse_args()

    fetcher = HttpSnapshotFetcher(
        SourceRegistry.from_path(),
        SnapshotWriter(LocalObjectStore(args.object_root)),
    )
    vdem = VDemAdapter(fetcher).fetch_latest_catalog()
    country_snapshot, countries = WorldBankAdapter(fetcher).fetch_country_catalog()
    payload = build_api_catalog(vdem, country_snapshot.sha256, countries)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "jurisdictions": len(payload["jurisdictions"]),
                "vdem_version": payload["eligibility"]["version"],
                "vdem_year": payload["eligibility"]["year"],
            }
        )
    )


if __name__ == "__main__":
    main()
