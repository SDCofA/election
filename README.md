# Elexion G20

Broadcast-grade election forecasting platform. Current vertical slice includes a Next.js command center, FastAPI forecast service, deterministic one-million-run simulation engine, declarative jurisdiction packs, pipeline assets, local infrastructure, Helm chart, and CI.

## Run

```powershell
uv sync --project services/api --dev
uv run --project services/api uvicorn app.main:app --reload --port 8000
pnpm install
$env:API_INTERNAL_URL='http://localhost:8000'
pnpm dev
```

Open `http://localhost:3000`. API documentation: `http://localhost:8000/docs`.

Full local stack, including PostGIS, MinIO immutable source snapshots, Dagster webserver, and scheduler daemon:

```powershell
docker compose -f infra/compose.yaml up --build
```

Dagster UI: `http://localhost:3001`. Licensed adapters fail closed; blocked sources cannot make network requests, but reference-only evidence may support an explicitly labeled D-grade scenario. Forecast publication compares the public baseline, Gaussian Monte Carlo, and Markov-momentum challengers under strict walk-forward gates. Forecast-enabled records publish exactly 1,000,000 deterministic simulations; countries without a defensible national probability target remain sourced calendar-only records.

Official calendar onboarding and immutable revision behavior: [docs/calendar-onboarding.md](docs/calendar-onboarding.md).

Governance: [completion audit](docs/completion-audit.md), [model selection](docs/model-governance.md), [historical evidence](docs/backtest-data-contract.md), [source licensing](docs/source-policy.md), [observability](docs/observability.md), [signed releases](docs/release.md), and [disaster recovery](docs/disaster-recovery.md).

## Verify

```powershell
pnpm typecheck
pnpm build
uv run --project services/api pytest services/api/tests
uv run --project services/api python services/api/scripts/load_smoke.py
uv run --project services/pipeline pytest services/pipeline/tests
pnpm --filter @elexion/web test:e2e
```
