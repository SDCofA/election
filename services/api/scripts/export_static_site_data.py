from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "apps" / "web" / "public" / "data"
ELECTION_IDS = (
    "us-2028-president",
    "gb-next-commons",
    "de-next-bundestag",
    "eu-2029-parliament",
    "eg-next-president",
    "au-next-chair",
    "se-2026-riksdag",
    "br-2026-president",
    "lv-2026-saeima",
    "il-2026-knesset",
    "nz-2026-general",
)


def write_json(relative_path: str, payload: object) -> None:
    target = OUTPUT / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def export_endpoint(client: TestClient, endpoint: str) -> bool:
    response = client.get(endpoint)
    if response.status_code == 404:
        return False
    response.raise_for_status()
    write_json(f"{endpoint.lstrip('/')}.json", response.json())
    return True


def main() -> None:
    shutil.rmtree(OUTPUT, ignore_errors=True)
    with TestClient(app) as client:
        for endpoint in ("/v1/catalog/status", "/v1/elections", "/v1/jurisdictions"):
            export_endpoint(client, endpoint)
        for election_id in ELECTION_IDS:
            root = f"/v1/elections/{election_id}"
            export_endpoint(client, root)
            for suffix in ("model-comparison", "forecasts", "coalitions", "mechanics", "sources"):
                export_endpoint(client, f"{root}/{suffix}")
            history = client.get(f"{root}/forecasts")
            if history.status_code == 200:
                for snapshot in history.json():
                    write_json(f"v1/forecast-snapshots/{snapshot['id']}.json", snapshot)
    shutil.copy2(
        ROOT / "packages" / "contracts" / "openapi-v1.json",
        OUTPUT / "openapi-v1.json",
    )


if __name__ == "__main__":
    main()
