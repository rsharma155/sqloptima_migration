# Release Notes

Version history and upgrade guidance for SQL Optima.

---

## Unreleased (working tree)

Documentation and control-plane polish aligned with the current codebase (2026-07-24), plus a **Docker-only product install**:

- **Website install package** — `deploy/install/` (compose + `sql-optima.cmd` / `.ps1` / `.sh`). Customers install Docker, download a zip from your site, and start. No compile, no Python/Node/Go on the host.
- **Production images** — API Dockerfile (ODBC Driver 18), `apps/ui/Dockerfile` (Next.js `standalone`), existing `Dockerfile.migration-engine`. CI: `.github/workflows/publish-images.yml`.
- **Helm** — chart deploys the Go engine and pulls `ghcr.io/rsharma155/sqloptima-*`.
- **Project scoping** — `shared/tenancy/project_scope.py` + Alembic `006`; non-admin JWTs with `project_id` are filtered on list/detail APIs.
- **Programs / Reports UI** — `/programs` and `/reports` nav entries wired to `/api/v1/programs` and `/api/v1/reports`.
- **Root docs refresh** — `CLAUDE.md`, `ARCHITECTURE.md`, `README.md`, `OPERATIONS.md`, `PACKAGING.md`, `SECURITY.md` updated for Go data plane, compose ports, and canonical root runbooks (not `docs/` copies).

No package version bump yet — still **0.2.0** until the next tagged release. Tag `v0.2.0` (or run **Publish install images**) so GHCR tags exist before sending customers the website zip.

---

## v0.2.0 — 2026-06-09

Replication hardening, platform capture tuning, migration control improvements, and developer-experience polish.

### Highlights

- **CDC capture reliability** — SQL Server changes are read from `cdc.<instance>_CT` change tables with correct 10-byte LSN parsing, capture-instance resolution from metadata, and checkpoint clamping when behind CDC retention.
- **Replication settings** — Poll interval and batch size are persisted in `platform_replication_settings`, exposed via admin API and **Settings → Replication**, and hot-reloaded on active capture agents.
- **Target table mapping** — Replication events preserve discovered PostgreSQL relnames (mixed-case tables from quoted DDL).
- **Migration pause/resume** — Jobs hydrate from metadata when absent from the in-memory registry; pause eligibility includes jobs with actively migrating tables.
- **RBAC in the UI** — Viewer accounts cannot access Settings or Admin routes; admin nav is hidden and direct navigation redirects with an error.
- **Bootstrap & startup** — `start.py` auto-creates `.venv`, optional prerequisite installers (`scripts/bootstrap_prereqs.*`), PostgreSQL metadata reachability checks, and Go queue path defaults to `data/migration_queue.bbolt`.

### Replication

- `SqlServerCdcProvider` queries change tables directly instead of `fn_cdc_get_all_changes_*` (avoids SQL Server error 313 for out-of-range LSN windows).
- LSN serialization fixed to `struct.pack(">IIH", …)` (10 bytes: VLF seq + block offset + slot).
- `CaptureAgent` supports runtime `set_poll_interval_ms()` / `set_batch_size()` with clamped bounds.
- Alembic migration `012_platform_replication_settings` adds the settings table.
- API: `GET/PUT /api/v1/admin/replication-settings` (viewer read, admin write).

### Migration & validation

- Pause/resume uses `_fetch_job_and_record()` to reconcile Go worker state from metadata DB.
- L2 PostgreSQL aggregates cast `AVG` through `NUMERIC` (fixes `round(double precision, int)` errors).
- Validation no longer auto-runs on page load; operators must click **Run Validation** explicitly.
- Validation JSON export recursively normalizes `Decimal`, `datetime`, `UUID`, and `bytes` for API responses.

### Platform & auth

- Login and registration trim usernames; empty usernames rejected.
- Login modal renders via React portal with improved contrast and autocomplete attributes.
- Stale JWT cleanup on app init (`purgeStaleAuth`).
- Admin can delete users via `DELETE /api/v1/admin/users/{user_id}`.
- Metadata DB auto-resets incompatible legacy Alembic layouts (dev only — data loss warning logged).

### SQL Server connector

- `execute()` accepts positional parameters in addition to dict-based params.
- `DECLARE` batches advance to the SELECT result set via `nextset()`.
- Batch primary-key discovery in schema introspection.

### Go data plane

- `MIGRATION_DATABASE_METADATA_URL` and `MIGRATION_QUEUE_PATH` env vars explicitly bound (override `default.toml`, especially on Windows).
- Default queue path moved from `/tmp/migration_queue.bbolt` to `data/migration_queue.bbolt`.

### Documentation

- [OPERATIONS.md](OPERATIONS.md) — day-2 runbooks (sizing, cutover, stuck jobs, error codes).
- [PACKAGING.md](PACKAGING.md) — product editions, license keys, Helm, metering, upgrades.

### Upgrade notes

1. Back up the metadata database (SQLite file or PostgreSQL dump).
2. Run `alembic upgrade head` (adds `platform_replication_settings`).
3. Restart API, UI, and Go migration-engine so env overrides and replication settings load.
4. If upgrading from a pre-GA metadata schema with `migration_jobs.id` PKs, dev environments may auto-reset schema on startup — back up first.

### Test coverage added

- `tests/unit/replicator/test_cdc_provider.py` — change-table query shape, LSN predicates, wildcard columns.
- `tests/unit/replicator/test_capture_agent_settings.py` — runtime poll/batch updates.
- `tests/unit/replicator/test_change_consumer.py` — target table name preservation.
- `tests/unit/test_pause_migration.py` — pause eligibility and metadata hydration.
- `tests/unit/test_replication_settings_config.py` — settings resolution.
- `engine-go/internal/config/env_override_test.go` — env wins over TOML.

---

## v0.1.0 — 2026-03-01

Initial public release of the SQL Optima migration platform.

### Highlights

- T-SQL → PL/pgSQL AST transpiler (SQLGlot + ANTLR4 fallback) with pgparse validation and auto-repair loop.
- Go migration-engine with adaptive PK chunking, bbolt queue, binary PostgreSQL `COPY`, and parallel workers.
- FastAPI control plane with JWT auth, migration dispatch, L1–L4 validation, and assessment reports.
- Next.js 15 UI: assessment, migration center, validation, schema comparison, SQL converter, replication preview.
- Phased post-migration finalize (identities, indexes, FKs), procedural object migration, and platform migration settings.
- Product editions, HMAC license enforcement, Helm chart, cutover workflows, and migration programs (enterprise).

See git history and [CONTRIBUTING.md](CONTRIBUTING.md) for the full v0.1.0 feature set.
