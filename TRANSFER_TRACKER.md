# Transfer (XDT) progress tracker

Cross-Database Transfer is a **third product path**. It must not write `migration_jobs`,
call `GoMigrationJobDispatcher`, run T-SQL conversion, or use `make_connector`
(role-typed source=MSSQL / target=PG).

Update this file whenever a slice lands or is blocked.

| Slice | Scope | Status |
|-------|--------|--------|
| 0 | Design: wizard, preflight, APIs, Go isolation | **done** |
| 1 | Control plane: `engine` on connections, `transfer_*` schema, `/api/v1/transfers`, `/transfers` UI, homogeneous preflight | **done** |
| 2 | Go data plane: claim `transfer_jobs`, `TransferDispatchConfig`, pause/resume/stop on `transfer_commands`, PostgreSQL→PostgreSQL extract/COPY (SQL Server→PG reuse) | **done** |
| 3 | Constraint disable / restore — operator review prompt, then execute accepted plan only | **done** |
| 4 | Homogeneous SQL Server→SQL Server bulk load | **done** |
| 5 | Heterogeneous PostgreSQL→SQL Server | pending |
| 6 | Worker applies live `transfer_runtime_settings` (chunk size / throttle) per chunk | partial (MSSQL→MSSQL only) |
| — | Platform Transfer settings + live per-table metrics/error logs | **done** |

## Platform Transfer settings (app-level)

- [x] Settings → Transfer: file offload enable, min rows (default 2,000,000), min MB, staging path
- [x] Persisted in `platform_transfer_settings` (Alembic `014`); snapshot into `transfer_jobs.config.file_offload`
- [x] Same-server copies never file-offload; worker reads the snapshot on claim
- [x] Live job dashboard lists every configured table (rows, %, status) and polls `/metrics`
- [x] Go writes `transfer_job_logs.table_name` and `transfer_table_plans.error` so each table's errors can be filtered

## Slice 4 checklist

- [x] `PathSupportsDataPlane("mssql_to_mssql")` — Go worker claims the job
- [x] No cursors, no `SELECT *` on batched copies, no default `NOLOCK`
- [x] Same instance: batched four-part `INSERT…SELECT` on integer keys (`@P1`/`@P2`)
- [x] Cross-server small: extract + `mssql.CopyIn` stream in chunk-sized batches
- [x] Cross-server large: native `bcp queryout -n` / `bcp in -n` when file offload is enabled; stream fallback if `bcp` is missing
- [x] Integer key-range advances `@Current = @RangeEnd + 1`; finite `MaxCopyIters`
- [x] Non-integer unique keys: keyset `TOP (@BatchSize)` with strictly advancing last key (not `OFFSET`)
- [x] Heap / no order column: one-shot only if estimate ≤ chunk size; otherwise fail
- [x] `SET IDENTITY_INSERT` / `bcp -E` when the copy includes identity columns
- [x] Row estimate from `sys.dm_db_partition_stats` (fallback `sys.partitions`); not `sp_spaceused`
- [x] Insert-only delta: skip when target max ≥ source max
- [x] Per-chunk progress + re-read live `chunk_size` on this path
- [ ] End-to-end copy against live SQL Server instances (operator verification)

## Slice 3 checklist

- [x] Destination constraint catalog from preflight (target-only)
- [x] API refuses start unless `operator_reviewed` is true
- [x] Default action is **keep**; disable is opt-in per object
- [x] Primary keys cannot be disabled
- [x] Wizard step lists destination objects and requires an explicit review checkbox
- [x] Go applies/restores only the accepted disable list (quoted DDL; no invented plan)

## Slice 2 checklist

- [x] Dispatch JSON `kind` is `"transfer"` in `transfer_jobs.config` (Python `create_job` + Go parse)
- [x] Go packages `internal/transfer` and `internal/extractport` (no `if path` on `MigrationGoJobHandler`)
- [x] Commands: table `transfer_commands`, NOTIFY / LISTEN channel `transfer_commands`
- [x] Metadata SQL against `transfer_*` only (claim, progress, logs, runtime settings)
- [x] Second worker loop in `migration-engine` (`go-transfer-worker-{pid}`)
- [x] Live mover: PostgreSQL→PostgreSQL `COPY`; SQL Server→PostgreSQL extract + `CopyFrom`
- [ ] End-to-end copy against live databases (operator verification)

## Conventions

- Python modules: `transfer_*.py` under `domains/transfer/`, `application/transfer_*.py`.
- Go files: `transfer_*.go` in `engine-go/internal/transfer/`.
- Tests first (TDD). Parameterized SQL only. Domain must not import FastAPI or SQLAlchemy.
