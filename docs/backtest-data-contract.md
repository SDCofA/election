# Historical Backtest Evidence Contract

Model promotion accepts only JSON datasets under `services/api/app/backtests/` referenced by a jurisdiction pack. Files use `schema_version: 3` and contain `source_revisions` plus chronological forecast-origin `records`. An election may have multiple records at different pre-election cutoffs, but its result truth must remain identical.

Each source revision requires a stable ID, HTTPS source URL, reuse license, retrieval date, repository-local raw snapshot path, and lowercase SHA-256 digest. Loading fails if the path escapes the approved directory, the raw object is absent, or its bytes no longer match the digest. Each election record must reference separate fundamentals, poll-snapshot, and official-result revisions. Synthetic or fixture IDs are rejected by the production loader.

Each record includes:

- election ID and election date;
- actual, fundamentals, and dated polling share vectors;
- forecast cutoff and source-availability dates;
- official-result availability date;
- fundamentals revision ID, one revision ID per poll snapshot, and result revision ID.

For each test origin, training chooses one prior origin per election at the nearest forecast horizon. Same-election records never enter training. Promotion fails closed unless leakage checks pass, at least eight origins cover at least three distinct held-out elections, source-vintage election history spans twenty years without gaps over eight years, every record has verified revision provenance, and the challenger passes election-clustered paired-bootstrap Brier superiority, vote-share RMSE, calibration, and empirical interval-coverage gates. Metric means weight elections equally, and clustering prevents elections with more cutoffs from overstating statistical significance. Every production model-fold uses 1,000,000 deterministic predictive draws; the count and full dataset SHA-256 are exposed through the model-comparison API.

The U.S. presidential benchmark contains 24 origins at 2, 6, 10, and 14 days before the 2000–2020 elections. Poll evidence is extracted from a content-pinned FiveThirtyEight CC BY 4.0 file; each aggregate contains only polls whose recorded poll date is at or before its cutoff. Official truth and prior-election fundamentals use FEC compilations of state-certified results. Because this is a short-horizon national-popular-vote benchmark—not a state-level Electoral College or early-cycle benchmark—the 2028 target horizon is outside its evaluated domain. The API may report the lower historical Brier score, but promotion remains blocked and the public baseline remains in service.

The one-million-draw report is materialized during the governed build rather than recomputed during API startup. Runtime loading verifies the report SHA-256, dataset SHA-256, exact target horizon, exact simulation count, and SHA-256 of the backtest engine source. Any dataset, algorithm, horizon, or report change therefore fails startup until the report is deliberately regenerated and reviewed.

No challenger is promoted until both evidence and deployment-horizon gates pass. Missing evidence produces `insufficient_historical_vintages`; out-of-domain evidence produces `insufficient_evidence`, never a synthetic winner.
