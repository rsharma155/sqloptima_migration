# SQL Optima Helm Chart

Deploy the migration platform API and UI to Kubernetes.

## Prerequisites

- Kubernetes 1.25+
- Helm 3.10+
- Container images built and pushed to your registry

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

See `values.yaml` for edition, resource limits, and metadata DB URL.
Set `MIGRATION_EDITION` to `assess`, `migrate`, `replicate`, or `enterprise` to gate features.
