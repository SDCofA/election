# Backtest evidence v3

Production challenger selection accepts only local, content-addressed schema-v3 datasets. Every
fundamentals, poll, and result revision must declare its role, HTTPS source and license URLs,
authority, SHA-256, and `observed_at <= released_at <= available_at <= retrieved_at` chronology.
Declared fundamentals and poll availability must exactly match each origin's cutoff evidence;
result availability must match the outcome revision. Unknown, unused, future, mis-typed, or
synthetic revisions fail closed.

Reliable comparison requires at least eight strict forecast-origin folds across three held-out
elections and at least twenty years of history without gaps over eight years. Training results
unavailable at a test cutoff are excluded. Gaussian and multi-contestant Markov challengers are
each tested against polls-only, fundamentals-only, and previous-election baselines. Each
model-fold uses 1,000,000 deterministically seeded predictive draws. Brier and calibration use
empirical simulated winner probabilities, while RMSE and empirical coverage use the simulated
share distribution and its 90% interval. This prevents a fixed-softmax approximation from hiding
differences between Gaussian and Markov uncertainty.

Multiple forecast origins may represent one election. Training is horizon-matched and excludes
the test election. Reported metric means weight elections equally; confidence intervals and
superiority tests resample election clusters rather than treating correlated origins as
independent evidence.

No challenger is promoted unless it passes familywise election-clustered paired-bootstrap Brier,
RMSE, empirical coverage, calibration, provenance, dataset-hash, and leakage gates.

One million simulations are required exactly at the API, pipeline publication, and database
boundaries. Seed derivation is deterministic from election and model version.
