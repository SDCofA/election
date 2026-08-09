# Source policy

Adapters check the packaged source registry before any network request. Missing or unapproved reuse terms block retrieval. Each immutable raw object records source ID, content hash, license ID and URL, attribution, and approved usage scope.

Current approved families include V-Dem, World Bank WDI, Eurostat-owned statistics under the Commission reuse decision, OECD-owned CPI observations under the OECD data permitted-use terms, geoBoundaries, UK Electoral Commission API data, German Federal Returning Officer open data, Brazil Superior Electoral Court open data under CC BY 4.0, Swedish Election Authority open data under its attribution terms, Latvia Central Election Commission datasets explicitly published under CC0 1.0, European Parliament election content under its reuse notice, FEC-authored election metadata/results as United States Government work, and the content-pinned FiveThirtyEight historical polling repository under CC BY 4.0. FiveThirtyEight data is approved only for reproducible historical backtesting, with attribution and source-commit preservation. Eurostat and OECD ingestion excludes data identified as third-party or otherwise restricted.

GDELT, IMF dataset-specific feeds, Egypt NEA, African Union content, Latvia CVK webpages, Israeli election-authority webpages, New Zealand Electoral Commission webpages, and International IDEA automated ingestion remain blocked until compatible terms or permission are recorded. International IDEA is reference-only because its standard terms restrict commercial benefit. No blocked source can make a network request.

The electoral-authority directory is link-only. Entries marked `LINK-ONLY-NO-INGESTION` provide an official destination for a public TBD record, but are not registered fetch adapters and cannot perform network retrieval. Their linked pages supply no extracted date, mechanics, contestant, or forecast value. Promotion to an ingestible source requires a separate registry decision with explicit reuse terms.

Parser confidence below the configured threshold triggers last-known-good canonical records with an explicit freshness warning. JSON, CSV, ICS, HTML, and text-extracted PDF contracts are supported.

Every changed canonical value appends a source revision linked to its immutable raw snapshot. Identical values are idempotent; changed releases receive monotonically increasing revision numbers. Quality A-C forecast publication requires exact input revision UUIDs whose source, availability time, and declared provenance all match the forecast cutoff.

Canonical macro feature snapshots query only observations already available and already observed at the forecast cutoff. Alternative official series are resolved by newest eligible vintage; future releases and future-dated periods are excluded. The snapshot preserves values, units, observation/release/availability timestamps, revisions, missing features, source URLs, licenses, and a deterministic SHA-256 digest.
