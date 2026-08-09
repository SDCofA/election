# Calendar onboarding

Catalog coverage advances in next-election-date order. Forecast availability is separate from
source-ingestion permission and final-ballot status. Unresolved official contestants or mechanics
produce an explicit grade-D scenario with possible candidates, parties, regional paths, or
governing-versus-opposition blocs; they no longer suppress the forecast.

Every authority-backed next-national-election record publishes a forecast. When no approved
reusable official calendar release has been captured, it uses a three-year planning horizon,
system `unresolved`, neutral 40/40/20 governing/opposition/other priors, and widened uncertainty.
It links to the official authority with `LINK-ONLY-NO-INGESTION`: no remote page bytes, text,
dates, or mechanics are copied. Catalog countries without even an authority-backed election
record remain visible as listings rather than invented elections.

Official calendar pages are checked daily through configured authority markers. Every successful
fetch is content-addressed in object storage. Semantic date/status changes append a new PostgreSQL
`calendar_revisions` row linked to its exact raw source revision; existing revisions are immutable.
Parser drift or outages retain the last known good revision, emit adapter health events, and cannot
publish a fresh calendar-change event. API workers re-read latest eligible revisions at most every
60 seconds, while published forecast snapshots remain immutable.

Current next-date additions:

- Sweden's 13 September 2026 Riksdag election is sourced to the Swedish Election Authority. Its
  current Riksdag parties form a possible field while final ballots remain authoritative.
- Brazil's 4 October 2026 presidential first round and 25 October runoff are sourced to TSE
  Resolution 23.751. Lula, Flávio Bolsonaro, and the residual field are modeled without claiming
  that party confirmation is the final TSE ballot.
- Latvia's Central Election Commission publishes fourteen official candidate lists. The site is
  citation-only, while a national-bloc proxy publishes wide intervals until the five-district
  translation is calibrated.
- Israel's current Knesset factions form the visible possible field. Final candidate lists and
  surplus-vote agreements widen uncertainty rather than blocking the forecast.
- New Zealand's registered parties form the possible field. Copyrighted webpages remain
  reference-only; automated retrieval stays blocked, while the D-grade forecast remains public.
