# Elexion G20

Election calendar and model-research platform. The current public website withholds numerical win probabilities when its available snapshot has grade D evidence. The repository retains reproducible simulation artifacts for method review.

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

Dagster UI: `http://localhost:3001`. Licensed adapters fail closed. A grade D structural simulation can be generated for research, but the public dashboard withholds its precise win probabilities because source-vintage feature inputs and jurisdiction-specific out-of-sample evidence are insufficient. One million draws reduce simulation noise; they do not establish predictive accuracy. If a live or static data request fails, the website shows an unavailable state and never substitutes hard-coded probabilities.

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
