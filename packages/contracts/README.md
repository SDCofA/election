# Public contracts

FastAPI OpenAPI at `/v1/openapi.json` is authoritative. Published fields are additive within v1. Forecast snapshots are immutable; clients resolve latest valid snapshots through election endpoints and retain snapshot IDs for replay.

Every forecast contains source provenance, data quality, freshness, model version/family, selection status, deterministic seed, and simulation count. `openapi-v1.json` is generated deterministically and checked for drift in CI.

```powershell
uv run --project services/api python services/api/scripts/export_openapi.py packages/contracts/openapi-v1.json
pnpm contracts
```
