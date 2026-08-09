# Poll source assessment — 2026-08-09

- FiveThirtyEight's public repository declares CC BY 4.0 for datasets and documents historical
  presidential poll files. The documented historical CSV endpoint now redirects to ABC News, so it
  fails the automated availability gate and is not registered as a live source.
- dawum.de exposes German federal and state polling through a JSON API under ODC-ODbL, with release
  date, fieldwork period, sample size, method, pollster, sponsor, and party results. Its documented
  coverage begins in 2017, so it cannot alone satisfy the twenty-year promotion requirement. ODbL
  attribution/share-alike obligations are recorded in the source registry. The approved adapter
  now ingests next-cycle Bundestag polls, stores raw snapshots and immutable poll revisions, and
  assigns a conservative next-day availability timestamp when only a publication date is supplied.

References: https://github.com/fivethirtyeight/data,
https://github.com/fivethirtyeight/data/tree/master/polls, https://dawum.de/API/.

The Federal Returning Officer publishes certified Bundestag results as machine-readable CSV under
DL-DE-BY-2.0. These results can supply outcome labels for 2017, 2021, and 2025, but they do not fill
the missing pre-2017 poll vintages. Consequently, a German-only reconstruction would produce too
few walk-forward folds and too short a time span; it is not admitted as promotion evidence.
