# Observability

The API exposes Prometheus text metrics at `/metrics`, including route/status counts, cumulative request-duration histogram buckets, rejected live events, and slow-client event drops. Responses carry `X-Request-ID`; stdout request logs are structured JSON and include route, status, latency, request ID, and OpenTelemetry trace ID without query strings or client identifiers.

Set `OTEL_EXPORTER_OTLP_ENDPOINT` (or `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`) to enable batched OTLP/HTTP traces. `OTEL_SERVICE_NAME` and `OTEL_DEPLOYMENT_ENVIRONMENT` configure resource identity. Production should send OTLP to a collector and route JSON stdout through the cluster logging agent.

Dagster has no public ingress by default. Enabling Helm `oidc.enabled` creates a dedicated oauth2-proxy ingress, restricts Dagster pod ingress to that proxy, and reads client/cookie credentials from the configured Kubernetes Secret. The deployment must provide an HTTPS host, issuer URL, TLS secret, and identity-provider client registration. Grafana is expected to use the same deployment OIDC policy in the cluster monitoring stack.

NATS subjects `elexion.events.forecast_publication`, `calendar_change`, `alert`, and `official_result_update` feed SSE subscribers. Event envelopes are rejected unless they contain timestamps, model/data-quality/freshness metadata, stable IDs, and provenance. Subscriber queues are bounded and exported drop counters expose slow-consumer pressure.

Set `monitoring.prometheusRule.enabled=true` when the Prometheus Operator CRDs are installed. The chart then creates executable alerts for absent API metrics, forecasts older than 25 hours, p95 latency above 300 ms, server-error rate above 5%, invalid live events, SSE backpressure, missing or stale Dagster success events, adapter fallbacks, and parser/source drift.

Dagster success/failure sensors append run events to PostgreSQL. Official calendar and result checkpoint stores append adapter success/failure events, distinguishing source unavailability, parser drift, and non-monotonic source drift. The API exports these durable counters and timestamps without relying on process-local state.

Additional deployment alerts:

- forecast freshness beyond the jurisdiction schedule;
- adapter failures or parser-confidence rejection;
- nonzero source-drift alarms;
- forecast publication latency and API p95 above 300 ms;
- invalid live-event envelopes, NATS disconnects, or dropped SSE messages;
- backup/restore drill failures and Kubernetes rollback events.

## Backup and recovery

Enable `backup.enabled` to run one non-overlapping PostgreSQL custom-format backup daily. The job uploads to the configured S3-compatible bucket with SSE-S3 (`AES256`) by default; use `aws:kms` plus `backup.kmsKeyId` for a deployment-owned KMS key. It verifies object length and SHA-256 metadata before success. `DATABASE_URL`, object-store credentials, and optional endpoint remain in the existing runtime Secret.

CI performs a real `pg_dump` plus isolated `pg_restore` on every database change. Production restore drills must download one backup, verify its `sha256` object metadata, restore into an isolated database with `pg_restore --exit-on-error`, run `002_smoke_test.sql`, and record the drill result in the deployment audit system before any recovery declaration.
