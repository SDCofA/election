# Completion audit

Audit date: 2026-08-11. `Implemented` means a repository artifact and automated contract exist. Quality and ingestion gates fail closed without suppressing exploratory forecasts: unsupported inputs cannot be fetched, and unsupported models cannot be promoted. `Operational proof required` means deployment credentials or a real production environment are outside this repository.

## User-critical forecast claims

| Requirement | Status | Evidence |
|---|---|---|
| Markov alternative versus Gaussian | Implemented | `backtest.py` evaluates both families from the same forecast origins, training sets, seeds, and one-million-draw count. `/model-comparison` publishes both plus three baselines. |
| Exactly 1,000,000 simulations | Implemented | Public, alternative, and model-fold schemas require exactly 1,000,000. Simulation invariants and deterministic replay are tested. |
| Reliable backtests | Implemented, promotion fail closed | U.S. dataset spans 2000–2020, retains source revision hashes and release vintages, uses 12 strict origins across three held-out elections, and reports Brier, RMSE, calibration, and interval coverage. Current 821-day target is outside the evaluated 2–14-day horizon, so neither challenger is promoted. |
| Baseline comparisons | Implemented | Polls-only, fundamentals-only, and previous-election baselines use identical folds and predictive draw counts. Automatic promotion requires paired-bootstrap Brier superiority plus RMSE, coverage, provenance, history, and horizon gates. |
| Reproducibility | Implemented | Seeds derive from election/model identity. The packaged report is bound to dataset, engine, target-horizon, and report SHA-256 hashes. |
| Driver sensitivity matrix | Implemented | API and dashboard vary one driver across the configured −1/+1 scale with every other input fixed, use the simulation's structural cap, and label results as vote-share shifts rather than causal or probability claims. |

## Platform and data

| Requirement | Status | Evidence |
|---|---|---|
| Next.js, FastAPI, Dagster | Implemented | Separate web, API, and pipeline packages; OpenAPI-generated TypeScript contract. |
| PostgreSQL/PostGIS, object storage, Redis, NATS | Implemented | Compose/Helm services, normalized SQL schema, immutable raw snapshot store, cache/rate-limit integration, durable NATS event boundary. |
| Normalized election domain | Implemented | Jurisdictions, systems, elections, districts, parties, candidates, coalitions, observations, source revisions, model versions, runs, snapshots, outcomes, and official results are represented in SQL. |
| Electoral-system engines | Implemented | Runoff, FPTP, proportional, mixed-member, electoral-college, and institutional validation/translation paths have golden and invariant tests. |
| Source licensing/provenance | Implemented | Registry blocks unapproved terms before fetch; raw content is hashed and immutable; canonical records retain revision IDs, four time clocks, license metadata, confidence, and last-known-good fallback. |
| Eligibility | Implemented | Public scope is pinned to the 19 sovereign G20 countries. The EU and AU are intentionally excluded. V-Dem status remains visible as model context rather than a public-scope rule. |
| Economic, governance, event, poll, and boundary adapters | Implemented where reuse is approved | Official sources, World Bank, OECD, Eurostat, Google News RSS, V-Dem, DAWUM, and geoBoundaries have adapters/contracts. Disallowed or reference-only sources are not fetched. |
| Hierarchical fundamentals and dynamic polls | Implemented | Leakage-safe empirical-Bayes partial pooling and time-decayed poll aggregation with mode quality, covariance, and house effects are unit-tested. Publication falls back to structural grade D where source-vintage inputs are unavailable. |

## G20 coverage

| Requirement | Status | Evidence |
|---|---|---|
| Every G20 country has a public record | Implemented | The 19 sovereign countries appear in the directory; unions and regional bodies do not. |
| Sourced election calendar | Implemented as dated source or link-only authority record | 13 G20 countries have a sourced election record; the remaining six stay listing-only. |
| Forecast for every sourced record | Implemented | All 13 sourced G20 election records publish one-million-run forecasts. Eight unresolved packs use an `exploratory_proxy` national-control scenario, a three-year horizon, possible fields, and grade D. |
| Public methodology and quality state | Implemented | Every election detail links methodology, mechanics, and sources. Forecasts expose A–D quality, freshness, missing drivers, and whether the field is official, possible, or scenario-only. |
| No candidate/licensing forecast block | Implemented | Final-list, timing, legal, mechanics, and reuse uncertainty widen intervals and lower quality. Reference-only pages are never ingested, but their licensing status does not erase the scenario. |

## Product and public interfaces

| Requirement | Status | Evidence |
|---|---|---|
| Command center and details | Implemented | G20 watch, searchable 19-country directory, possible-field cards, probability gauge, vote/seat intervals, parliament layout, coalition simulator, ticker, immutable history, methodology, and source ledger. |
| Maps | Fail closed without validated subnational evidence | GeoJSON endpoint exists; current forecasts suppress regional maps and explain the missing boundary/input gate. |
| REST/OpenAPI and replay | Implemented | Versioned catalog, calendar, detail, snapshot, simulation, drivers, backtest, source, map, mechanics, coalition, and official-result routes; snapshot IDs are immutable and replayable. |
| SSE | Implemented | Forecast, calendar, alert, result, and heartbeat envelopes require timestamps, model version, quality, freshness, and provenance. Replay and slow-client drop metrics are tested. |
| Live results | Implemented where official feed configured; otherwise explicit unavailable | Adapter enforces reporting units, monotonicity, provenance, certification state, and last-known-good recovery. The public route never fabricates totals. |
| Accessibility/responsiveness | Implemented | Translation keys, locale formatting, RTL logical layout, reduced motion, keyboard/touch checks, automated WCAG 2.2 AA scans, mobile overflow test, and visual regression. |
| Performance | Implemented on reference CI path | Cached API p95 gate is 300 ms; browser LCP gate is 2.5 s. Production telemetry repeats both thresholds. |

## Security and operations

| Requirement | Status | Evidence |
|---|---|---|
| Public-edge controls | Implemented | CSP/security headers, trusted hosts, rate limiting, bounded proxy paths, internal token boundary, audit triggers, and no voter-personal-data schema. |
| OIDC operations | Implemented in Helm | Dagster, Grafana, and operational ingress are disabled unless OIDC values are complete. |
| CI/CD supply chain | Implemented | Checks, multi-architecture builds, SBOMs, Trivy scans, keyless signing, signature verification, OIDC deploy, canary analysis, health rollback, and migration hooks. |
| Observability | Implemented | OpenTelemetry, Prometheus metrics/rules, durable pipeline/adapter telemetry, logs, freshness, latency, failure, drift, SSE, and source-age alarms. |
| Backups/restores | Implemented and CI-drilled | Encrypted/checksummed backup job plus isolated PostgreSQL dump/restore smoke drill. Production restore evidence remains an operational responsibility. |
| Real production rollout | Operational proof required | Repository cannot prove a live cluster, DNS/TLS, identity provider, registry, external alert delivery, real backup retention, or authority-feed credentials without environment access. Production coverage must not be declared solely from local tests. |

## Honest publication conclusion

The software contract separates forecast availability from model promotion. It does not claim that Markov is universally better: Markov leads historical U.S. short-horizon Brier score but has materially worse interval coverage, and the live target horizon is unsupported. Türkiye has zero verified out-of-sample folds; its probability is an exploratory scenario, not a backtested verdict. The eight G20 authority-reference scenarios remain grade D until reproducible evidence replaces their neutral priors.
