from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

os.environ.setdefault("ELEXION_RATE_LIMIT_PER_MINUTE", "10000")

from app.main import app  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "apps" / "web" / "public" / "data"
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
        export_endpoint(client, "/v1/catalog/status")
        election_response = client.get("/v1/elections")
        election_response.raise_for_status()
        elections = election_response.json()
        write_json("v1/elections.json", elections)
        export_endpoint(client, "/v1/jurisdictions")
        for election_id in (item["id"] for item in elections):
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
