# Disaster recovery runbook

## Recovery objectives

- PostgreSQL/PostGIS: point-in-time recovery target; verify quarterly.
- S3-compatible snapshots: versioning/object lock; immutable raw and published objects.
- Redis/NATS: disposable coordination state; rebuild from PostgreSQL and object storage.

## Restore drill

1. Freeze publication schedules and record latest live forecast snapshot IDs.
2. Restore PostgreSQL into an isolated namespace; never overwrite production during a drill.
3. Validate schema, row counts, foreign keys, latest forecast IDs, and immutable-trigger behavior.
4. Restore or mount object-store replica; verify hashes referenced by source and forecast manifests.
5. Start API read-only against restored state; replay catalog, forecast, source, and result contract tests.
6. Resume one canary Dagster daemon; materialize source policy and validation assets without publishing.
7. Compare recovered latest snapshots byte-for-byte with pre-drill IDs.
8. Record recovery time, data-loss window, failed checks, and remediation owner before unfreezing.

Production credentials, encryption keys, bucket versioning, backup schedules, and OIDC policies must be supplied by the deployment environment. Local Compose is not a backup system.
