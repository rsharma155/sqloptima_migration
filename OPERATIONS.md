# Operations Guide

Day-2 runbook for operating the SQL Server → PostgreSQL migration platform.

## Sizing

| Table size | Workers | Chunk size | Expected duration |
|------------|---------|------------|-------------------|
| < 10M rows | 1–2 | 10,000 | 1–4 hours |
| 10M–100M | 4–8 | 25,000 | 4–24 hours |
| 100M–1B | 8–16 | 50,000 | 1–7 days |

See `GET /api/v1/admin/slos` for published SLO targets.

## Health checks

- API: `GET /health` (unauthenticated)
- Metrics: `GET /metrics` (Prometheus)
- Diagnostics: `GET /api/v1/admin/diagnostics` (ADMIN)

## Snapshot gate

Before destructive loads, migration start verifies a target backup unless disabled:

- Pass `snapshot_ref` pointing to a verified `pg_dump` file, or
- Let the platform create one (requires `pg_dump` on PATH), or
- Dev override: `MIGRATION_ALLOW_NO_SNAPSHOT=1`, or
- API: `require_target_snapshot: false`

## PII masking

Use `masking_policy: "auto"` on `POST /api/v1/migrations` to discover and mask sensitive columns.
Use `"strict"` in regulated environments — fails if sensitive columns would remain unmasked.

## Cutover workflow

1. `POST /api/v1/workflows/cutover/start`
2. Verify validation + snapshot
3. `POST /api/v1/workflows/cutover/approve` (human gate)
4. On failure: `POST /api/v1/workflows/cutover/rollback`
5. Connection switch manifest: `GET /api/v1/workflows/cutover/{id}/connection-switch`

## Stuck jobs

1. Check job status: `GET /api/v1/migrations/{job_id}`
2. Review `/metrics` throughput counters
3. Pause: `POST /api/v1/migrations/{job_id}/pause`
4. Resume: `POST /api/v1/migrations/{job_id}/resume`
5. Stale chunk leases reset automatically on worker restart; check metadata DB `migration_commands`

## Connection errors

| Symptom | Error code | Action |
|---------|------------|--------|
| Login failed | `CONN_AUTH_FAILED` | Verify credentials in Connections |
| SQL Server timeout | `CONN_SOURCE_UNREACHABLE` | Check firewall, port 1433, SQL Browser |
| PostgreSQL refused | `CONN_TARGET_UNREACHABLE` | Check `pg_hba.conf`, port 5432 |
| Snapshot blocked | `MIG_SNAPSHOT_REQUIRED` | Run `pg_dump` or pass `snapshot_ref` |

API errors return `error_code`, `cause`, and `remediation` (not raw driver traces).

## Least-privilege accounts

Apply scripts in `docs/sql/least_privilege_grants.sql` before production migrations.
`PreMigrationValidator.validate_privileges()` warns if `sysadmin` or PostgreSQL `superuser` is used.

## Programs and waves

Group tables into phased cutovers:

- `POST /api/v1/programs` — create program under a project
- `POST /api/v1/programs/{id}/waves` — add table wave
- `POST /api/v1/programs/waves/{id}/sign-off` — approver sign-off

## Notifications

Set `MIGRATION_WEBHOOK_URL` for job start/complete/fail webhooks.

## E2E equivalence CI

Weekly GitHub workflow runs live procedure/query equivalence against docker-compose sample DBs.
Local: `MIGRATION_E2E_PROC_EQ=1 python -m pytest tests/integration/test_procedure_equivalence_live.py -v`
