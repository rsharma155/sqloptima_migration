# Packaging & Licensing

## Editions

Set `MIGRATION_EDITION` to gate features:

| Edition | `MIGRATION_EDITION` | Features |
|---------|---------------------|----------|
| Assess | `assess` | Discovery, assessment, reports |
| Migrate | `migrate` | + migration, validation |
| Replicate | `replicate` | + replication, cutover |
| Enterprise | `enterprise` | + programs, multi-project, audit export (default) |

Check runtime: `GET /api/v1/admin/edition`

## Deployment

| Mode | How |
|------|-----|
| On-prem Docker | `docker-compose up` or `docker-compose --profile sample-dbs up` |
| Kubernetes | `helm install sql-optima ./deploy/helm/sql-optima` (see chart README) |
| SaaS | One deployment per tenant recommended until row-level tenancy is fully enforced |

Set `MIGRATION_DEPLOYMENT=on-prem|saas|k8s`.

## License keys

Production deployments must set `MIGRATION_LICENSE_KEY`. Development accepts `DEV-LOCAL` when `MIGRATION_ENV` is not `production`.

Generate a key for an edition (operator tooling):

```python
from domains.licensing.license_enforcement import generate_license_key
from domains.licensing.editions import ProductEdition
print(generate_license_key(ProductEdition.MIGRATE))
```

Set `MIGRATION_LICENSE_SECRET` (or reuse `MIGRATION_MASTER_KEY`) as the HMAC signing secret. Migration start and edition-gated APIs call `require_valid_license()` / `require_feature()`.

## Metering

Usage signals for billing pilots:

`GET /api/v1/admin/usage?days=30`

Returns migration jobs started, rows migrated, audit events, and login count.

## Upgrades

1. Back up metadata DB (SQLite file or Postgres dump).
2. Run `alembic upgrade head`.
3. Rotate `MIGRATION_JWT_SECRET` — set `MIGRATION_JWT_SECRET_PREVIOUS` to the old value during rotation window.
4. Restart API + worker.

## SBOM

```bash
python scripts/generate_sbom.py
# → dist/sbom-python.json
```

Weekly CI generates and uploads the SBOM artifact.
