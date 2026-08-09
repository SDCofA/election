# Model governance

Public forecasts fail closed. The default public family is `baseline_ensemble` until a challenger passes all strict walk-forward gates.

## Challenger comparison

- `gaussian_monte_carlo`: continuous exchangeable, zero-sum multi-contestant campaign shocks; no contestant-order sign convention.
- `markov_momentum`: persistent three-state campaign movement model with training-only transition,
  step-size, and horizon estimates.
- Required baselines: polls-only, fundamentals-only, previous-election.
- Minimum evidence: eight source-vintage forecast-origin folds across three held-out elections and twenty years of history without gaps over eight years, with immutable revision hashes and observed/released/available/retrieved chronology for fundamentals, every poll snapshot, and official results.
- Promotion: every model-fold generates 1,000,000 deterministic predictive draws. Each challenger is tested separately against the best baseline with familywise election-clustered paired-bootstrap 90% superiority; eligible models also need RMSE within 5% of baseline, at least 80% empirical interval coverage, calibration error no higher than 10% and no more than one point worse than baseline, and no leakage.

Each published snapshot records model version, seed, one-million simulation count, exact input revision UUIDs, source manifest, quality grade, and immutable content hash. Failed or anomalous runs leave the prior snapshot live.

Before simulation publication, the pipeline builds a `canonical-macro-v1` feature snapshot directly from PostgreSQL observations after poll persistence completes. Selection requires `observed_at`, `available_at`, and raw-source `retrieved_at` at or before `as_of`, chooses the latest eligible revision for each required macro feature, records missingness and exact source-revision UUIDs, and persists the content-addressed snapshot append-only. Quality A-C publication fails if required macro evidence is incomplete or omitted from forecast lineage. Object-storage and NATS publication also fail closed unless the forecast transaction is durably recorded in PostgreSQL.

Candidate generation runs behind an authenticated internal API boundary. It selects only poll revisions available and retrieved by the macro snapshot cutoff, normalizes all-contestant shares, and blends polling with the jurisdiction prior using a bounded horizon weight (25%-72%) multiplied by a 90-day staleness decay. Poll covariance can widen uncertainty; polls older than 45 days prevent quality A-C. Growth, inflation, and unemployment supply a capped fundamental shift. Exact macro and poll revision UUIDs and licensed provenance are embedded in each candidate. The pipeline requests the backtest-selected family, validates one-million simulations and lineage, then persists before publication.

The U.S. pack has 12 real short-horizon forecast-origin folds across the 2012, 2016, and 2020 held-out elections, backed by a 2000–2020 content-addressed dataset. Markov leads historical Brier score; Gaussian leads vote-share RMSE and interval coverage. Neither is promoted because the evidence covers only 2–14 days before election day while the current 2028 target is hundreds of days away. The baseline therefore remains public by design.

Representative forecasts without an attached source-vintage feature snapshot are forced to quality grade D, marked structural-only, and expose zero model-input sources. Calendar citations never count as polling or fundamentals provenance.
