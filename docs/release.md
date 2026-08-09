# Signed release and deployment

The `Release` workflow starts only after successful `CI` on the default branch, or by a manual run.
It publishes API, pipeline, and web images to GHCR for `linux/amd64` and `linux/arm64`. BuildKit
attaches maximal provenance and an OCI SBOM; the workflow also uploads SPDX JSON, scans each
published digest for high/critical vulnerabilities, and keyless-signs the immutable digest with
the GitHub Actions OIDC identity.

Production deployment is enabled only when repository variables `KUBE_SERVER` and
`KUBE_OIDC_AUDIENCE` exist. Optional variables are `KUBE_NAMESPACE` and `HELM_RELEASE`. The
`production` environment must contain `KUBE_CA_CERT`, a base64-encoded cluster CA. The Kubernetes
API must trust GitHub's OIDC issuer for the configured audience and authorize the constrained
repository/workflow claims. No long-lived kubeconfig or cloud credential is stored.

The deploy job verifies every Cosign signature before use. Existing releases receive isolated API
and web canaries addressed by digest, in-cluster health probes, then atomic promotion of API, web,
and pipeline. Any failure rolls back to the exact pre-canary Helm revision and verifies the stable
rollout. First installation uses Helm `--atomic`; later releases always take the canary path.

Before install or upgrade, a Helm hook runs ordered PostgreSQL migrations from the candidate
pipeline image. It takes a transaction-scoped advisory lock, records SHA-256 checksums in
`schema_migrations`, rejects changed history or partial unmanaged schemas, and is safe to rerun.
Migrations must remain backward-compatible because application rollback does not reverse data
definition changes.

Private GHCR deployments can set Helm `imagePullSecrets` to pre-created registry credentials.
The runtime Secret named by `secrets.existingSecret` must provide `ELEXION_INTERNAL_TOKEN` with a
high-entropy value shared only by API and pipeline pods. Candidate generation returns 503 when the
token is absent and 403 when it is invalid.
