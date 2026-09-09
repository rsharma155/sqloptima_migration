# Packaging & Licensing

## End-user install (no compile)

Ship **pre-built container images**. Customers install Docker only.

1. Publish images (`sqloptima-api`, `sqloptima-ui`, `sqloptima-engine`) to GHCR via `.github/workflows/publish-images.yml`.
2. Mark those packages **public**.
3. Host `deploy/install/` (or `dist/sql-optima-install.zip` from the workflow) on your **website**.
4. Customer: install Docker → download zip → `sql-optima.cmd` / `./sql-optima.sh`.

See [deploy/install/INSTALL.md](deploy/install/INSTALL.md). Do not send customers to `git clone` or `python start.py`.

The installer compose file is `deploy/install/docker-compose.yml`. Root `docker-compose.yml` remains the **developer** observability stack (Grafana on host 3508, source bind-mounts).

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
| On-prem Docker (product) | `deploy/install/sql-optima.sh` or `sql-optima.ps1` — pulls GHCR images |
| On-prem Docker (lab / source) | `docker compose up` from the repo |
| Kubernetes | `helm install sql-optima ./deploy/helm/sql-optima` (API + UI + engine) |
| SaaS | One deployment per tenant recommended; JWT `project_id` scoping (`shared/tenancy/`) is available — treat full multi-tenant isolation as partial until all resources are project-bound |

Set `MIGRATION_DEPLOYMENT=on-prem|saas|k8s`.

## License keys

Production (`MIGRATION_ENV=production`) must set a real `MIGRATION_LICENSE_KEY`. The Docker installer defaults to `MIGRATION_ENV=on-prem` so `DEV-LOCAL` is accepted for first-run. Development also accepts `DEV-LOCAL` when `MIGRATION_ENV` is not `production`.

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

**Docker install:** bump `SQLOPTIMA_VERSION` in `.env`, then re-run the start script (`compose pull` + `up`). Keep the same `MIGRATION_MASTER_KEY` or encrypted connection passwords will not decrypt.

**Source / Helm:**

1. Back up metadata DB (PostgreSQL dump preferred; SQLite file only if still on the zero-config path).
2. The API applies Alembic on startup (`init_db`). For a source checkout you can also run `alembic upgrade head`.
3. Rotate `MIGRATION_JWT_SECRET` — set `MIGRATION_JWT_SECRET_PREVIOUS` to the old value during the rotation window.
4. Restart API, UI, and **Go migration-engine**.

## SBOM

```bash
python scripts/generate_sbom.py
# → dist/sbom-python.json
```

Weekly CI generates and uploads the SBOM artifact. Release CI also uploads `sql-optima-install.zip`.
