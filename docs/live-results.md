# Official live results

Dagster runs `refresh_official_results` every minute. Polling remains zero-network unless a
jurisdiction pack declares an `official_results.status` of `approved`, references an approved
source adapter and election citation, supplies canonical reporting units, and the current UTC
time is inside its timezone-aware `live_window`.

Feeds are HTTPS/host allowlisted by the source registry. JSON and CSV contracts require at least
98% parser confidence. Vote totals, reporting fractions, and timestamps cannot move backwards.
Parser or source drift serves the last-known-good checkpoint with a warning; fallback batches are
never inserted or published as fresh results.

Fresh batches and their exact raw-source snapshot are committed to PostgreSQL before a
metadata-complete `official_result_update` is sent to NATS. Unknown reporting units or contestants,
unapproved sources, missing provenance, absent durable storage, and malformed configurations fail
closed. Packs without an approved feed remain explicitly unavailable and cause no network calls.
