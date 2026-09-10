# SQL Optima Migration Helm Chart

Deploy the migration platform API, UI, and Go data plane to Kubernetes.

## Prerequisites

- Kubernetes 1.25+
- Helm 3.10+
- Published images (`ghcr.io/rsharma155/sqloptima_migration-api`, `sqloptima_migration-ui`, `sqloptima_migration-engine`)

Laptop / VM users should **not** use Helm. Use the Docker-only package in `deploy/install/` (see [INSTALL.md](../install/INSTALL.md)).

## Install

```bash
helm install sql-optima ./deploy/helm/sql-optima \
  --set env.MIGRATION_EDITION=enterprise \
  --set-file env.MIGRATION_LICENSE_KEY=<(echo -n "$MIGRATION_LICENSE_KEY")
```

Create secrets before install in production:

```bash
kubectl create secret generic sql-optima-sql-optima-secrets \
  --from-literal=jwt-secret="$MIGRATION_JWT_SECRET" \
  --from-literal=master-key="$MIGRATION_MASTER_KEY" \
  --from-literal=license-key="$MIGRATION_LICENSE_KEY"
```

## Configuration

See `values.yaml` for edition, image tags, resource limits, and metadata DB URL.
Set `MIGRATION_EDITION` to `assess`, `migrate`, `replicate`, or `enterprise` to gate features.
