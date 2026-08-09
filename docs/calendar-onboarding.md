# Calendar onboarding

Catalog coverage advances in next-election-date order. A jurisdiction becomes `calendar_only` only
after an election-authority source, approved reuse terms, a validated system pack, and a dated
calendar assertion are present. Unresolved official contestants or mechanics remain explicit
blocking reasons; they are never replaced with speculative names.

Every catalog jurisdiction has a public next-national-election record. When no approved reusable
official calendar release has been captured, the record uses a nullable date with confidence
`tbd`, system `unresolved`, and coverage `mechanics_blocked`. It links to the official electoral
authority for human verification but uses `LINK-ONLY-NO-INGESTION`: no remote page bytes, text,
dates, or mechanics are copied. These records improve discoverability without masquerading as
validated calendars. They move to dated `calendar_only` or forecast coverage only through the
normal licensed-adapter and mechanics-validation gates.

Official calendar pages are checked daily through configured authority markers. Every successful
fetch is content-addressed in object storage. Semantic date/status changes append a new PostgreSQL
`calendar_revisions` row linked to its exact raw source revision; existing revisions are immutable.
Parser drift or outages retain the last known good revision, emit adapter health events, and cannot
publish a fresh calendar-change event. API workers re-read latest eligible revisions at most every
60 seconds, while published forecast snapshots remain immutable.

Current next-date additions:

- Sweden's 13 September 2026 Riksdag election is sourced to the Swedish Election Authority. It
  remains calendar-only until the still-open official party/candidate process is final.
- Brazil's 4 October 2026 presidential first round and 25 October runoff are sourced to TSE
  Resolution 23.751. It remains calendar-only until official candidate registration resolves the
  contestant field.
- Latvia's official site states a 3 October 2026 Saeima election and the Central Election
  Commission has fixed the 100-seat district split. The site is all-rights-reserved, so it is
  citation-only and no automated calendar snapshot is admitted. Only separately published CC0
  open datasets are approved. The pack remains mechanics- and license-blocked.
- Israel's Central Elections Committee timeline states a 27 October 2026 Knesset election. The
  120-seat national proportional system and 3.25% threshold are sourced to the Knesset. Official
  pages remain citation-only because machine-reuse terms are not approved; candidate lists and
  surplus-vote agreements are also unresolved.
- New Zealand's Electoral Commission confirms the 7 November 2026 general election, 71 final
  electorates, and 120-seat Sainte-Laguë MMP with a 5% or one-electorate qualification rule.
  Candidate and party lists remain unresolved until 8 October. The cited webpages carry a
  copyright notice without approved machine-reuse terms, so automated retrieval stays blocked.
