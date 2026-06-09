# SQL Optima — SQL Server → PostgreSQL Migration Platform

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Go 1.23+](https://img.shields.io/badge/Go-1.23+-00ADD8?logo=go&logoColor=white)](https://go.dev/)
[![Next.js 15](https://img.shields.io/badge/Next.js-15-000000?logo=next.js&logoColor=white)](https://nextjs.org/)
[![GitHub](https://img.shields.io/badge/GitHub-sqloptima__migration-181717?logo=github)](https://github.com/rsharma155/sqloptima_migration)

**Repository:** [github.com/rsharma155/sqloptima_migration](https://github.com/rsharma155/sqloptima_migration)

**SQL Optima** is a full-stack migration platform that automates the transition from Microsoft SQL Server to PostgreSQL. It treats migration as a **compilation problem** — parsing T-SQL into an AST and re-emitting idiomatic PL/pgSQL — rather than applying fragile regex substitutions. Bulk data movement runs in a dedicated **Go data plane** (`engine-go/`) with adaptive chunking, a crash-safe bbolt queue, and PostgreSQL binary `COPY`; Python provides the control plane (API, dispatch, validation, UI).

---

## One-Command Quickstart

> **Prerequisites:** Python 3.11+, Node.js 18+, npm, Go 1.23+ (for data migration), Docker (recommended — metadata PostgreSQL). Missing toolchains can be auto-installed via `scripts/bootstrap_prereqs.sh` / `bootstrap_prereqs.ps1` when you use `./start.sh` or `.\start.ps1`.

Copy and paste this into a terminal — it clones the repo and starts the full stack (API + UI + Go migration-engine):

```bash
git clone https://github.com/rsharma155/sqloptima_migration.git && cd sqloptima_migration && python3 start.py --all
```

On Windows, use `python` instead of `python3` if needed:

```powershell
git clone https://github.com/rsharma155/sqloptima_migration.git; cd sqloptima_migration; python start.py --all
```

Platform-specific wrappers (after clone, create `.venv` first if you prefer, then delegate to `start.py`):

```bash
./start.sh --all          # Linux / macOS
.\start.ps1 -all          # Windows PowerShell
```

`start.py --all` will:

1. Check Python, Node.js, and Go toolchains
2. Generate a `.env` file with secure random keys (first run only)
3. Install Python and npm dependencies
4. Start the metadata database container (`postgres_checklist`, Docker if available)
5. Apply metadata DB migrations
6. Launch the **FastAPI** control plane on **port 8508**
7. Launch the **Go migration-engine** data plane (polls metadata, runs extract→load)
8. Launch the **Next.js** frontend on **port 3508**
9. **Open `http://localhost:3508` in your default browser**

On first launch you will be redirected to the **Setup** page to create an admin account. After that, you land on the **Dashboard** every time.

> **Tip — skip the interactive menu:**
>
> ```bash
> python start.py --all       # API + UI + Go engine (recommended)
> python start.py --api       # Control plane only (migrations won't run without the engine)
> python start.py --engine    # Go migration-engine only
> python start.py --ui        # Frontend only
> python start.py --setup     # Install deps, do not start servers
> python start.py --test      # Run the test suite
> ```

---

## Service URLs


| Service            | URL                                                   | Description                                                  |
| ------------------ | ----------------------------------------------------- | ------------------------------------------------------------ |
| Dashboard (UI)     | `http://localhost:3508`                               | Main web interface                                           |
| REST API           | `http://localhost:8508`                               | FastAPI control plane                                        |
| Swagger / OpenAPI  | `http://localhost:8508/docs`                          | Interactive API explorer                                     |
| Health check       | `http://localhost:8508/health`                        | Unauthenticated liveness probe                               |
| Prometheus metrics | `http://localhost:8508/metrics`                       | Platform counters (rows migrated, chunk duration, queue lag) |
| Go engine health   | `http://localhost:8508/api/v1/admin/go-engine/health` | Worker heartbeat (requires admin JWT)                        |
| SLO targets        | `http://localhost:8508/api/v1/admin/slos`             | Published SLOs and capacity guidance (requires JWT)          |


---

## Why SQL Optima?

Migrating from SQL Server to PostgreSQL is hard due to deep differences in procedural logic, data types, and proprietary features. SQL Optima handles these differences systematically:


| Challenge             | How SQL Optima Handles It                                                                                                                                |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Complex T-SQL logic   | Multi-pass AST transpiler (SQLGlot + ANTLR4 fallback) with T-SQL parse unblockers, pgparse validation, and an auto-repair loop — never regex on full SQL |
| Bulk data movement    | Go engine: half-open PK chunk boundaries, adaptive chunking, bbolt crash-safe queue, binary `COPY`, parallel workers                                     |
| PII / compliance      | Column transforms (`mask_hash`, `mask_tokenize`, …) with `masking_policy: auto\|strict` discovery via `pii_classifier`                                    |
| Staying in sync       | 9-state CDC finite state machine (snapshot → streaming)                                                                                                  |
| Trust & correctness   | L1–L4 validation: row counts, aggregates, chunk hashing, statistical sampling; optional procedure/query equivalence harnesses                            |
| Production cutover    | Snapshot gate (`pg_dump`), cutover checkpoints, write-freeze, rollback window, connection-switch manifest                                                |
| Schema differences    | 40+ function mappings, configurable schema renaming, identifier quoting                                                                                  |
| Commercial deployment | Product editions (`assess` / `migrate` / `replicate` / `enterprise`), HMAC license keys, Helm chart, usage metering                                      |


---

## The Migration Lifecycle

SQL Optima guides you through five stages, each backed by its own UI page:

```
1. Assess  →  2. Convert  →  3. Migrate  →  4. Validate  →  5. Sync (CDC)
```

### 1. Assess

Connect to SQL Server and get an instant readiness report. Every table is scored `SAFE`, `WARNING`, or `BLOCKER`. Complexity scores and estimated migration times give you a clear roadmap before writing a single line of migration code.

### 2. Convert

Automated schema and logic conversion with 40+ built-in function mappings (`GETDATE()` → `CURRENT_TIMESTAMP`, `ISNULL` → `COALESCE`, etc.). Full support for `MERGE`, `OUTPUT`, `CURSOR`, `RAISERROR`, `TOP`, and other T-SQL constructs.

The conversion pipeline has three hardening stages beyond raw AST transpilation:

1. **Parse unblockers** — normalize T-SQL before parsing (strip `GO`, session `SET` lines, bracket identifiers, table hints) so SQLGlot/ANTLR can parse real-world scripts
2. **AST transpilation** — SQLGlot primary, ANTLR4 fallback; all transforms on AST nodes
3. **Repair loop** — `PostgresSyntaxValidator` (pgparse) validates output; `ConversionRepairService` applies rule-based fixers in up to 3 rounds until syntax passes or repairs exhaust

The SQL Converter UI surfaces `parse_unblockers_applied`, auto-repair counts, and a `manual_review_required` flag when pgparse still fails.

### 3. Migrate

High-throughput **Go data plane** (`engine-go/cmd/migration-engine`). Python dispatches jobs to metadata PostgreSQL; the Go worker claims them, plans PK/datetime/UUID chunks, enqueues work in an embedded **bbolt** queue, extracts via `go-mssqldb`, and loads with PostgreSQL binary `COPY`. Chunk sizes adapt to observed latency; failed chunks retry with `[0, 30, 120]s` backoff and quarantine on exhaustion. Pause/stop/resume flows through `migration_commands` + `NOTIFY`.

The **Migration Center** wizard auto-runs a readiness **assessment** after table discovery. Each table shows a `SAFE` / `WARNING` / `BLOCKER` badge with expandable details (blockers, warnings, LOB columns, prerequisites). Tables with blockers cannot be started until resolved.

Additional migration safeguards shipped in the GA polish pass:

- **Snapshot gate** — by default `require_target_snapshot: true` blocks migration until a target `pg_dump` snapshot exists (override dev-only via `MIGRATION_ALLOW_NO_SNAPSHOT=1`)
- **PII masking** — `masking_policy: none|auto|strict` with per-column transforms (`mask_hash`, `mask_nullify`, `mask_tokenize`, …) wired through to the Go data plane
- **License enforcement** — migration start calls `require_valid_license()` and edition feature gates (`MIGRATION_EDITION`, `MIGRATION_LICENSE_KEY`)
- **Chunk boundary fix** — PK/datetime chunk planners use half-open `[start, end)` intervals aligned with extraction queries (no silent row skips)

### 4. Validate

Four validation tiers (L1–L4) run against source and target with correct `target_schema` scoping:


| Level  | What it checks                                                                |
| ------ | ----------------------------------------------------------------------------- |
| **L1** | Row counts                                                                    |
| **L2** | Per-column aggregates (MIN/MAX/SUM) with function types and failure summaries |
| **L3** | Chunk-level count/hash pushdown                                               |
| **L4** | Statistical row sampling                                                      |


Validation is **manual** — click **Run Validation** to start. L1 is lightweight; L2/L3 run full-table aggregate scans on the source (avoid on large production tables during peak hours). A **row sample compare** fetches the top 10 rows from source and target sorted by primary key (or unique index).

### 5. Sync (Replication / CDC)

Keep the target database in sync after bulk migration. **SQL Server CDC must be enabled** on the source database and on each replicated table (`sys.sp_cdc_enable_db` / `sys.sp_cdc_enable_table`). The API and UI block stream creation when CDC is not ready.

The Python replication stack (`apps/replicator/`) is wired to the API and UI:

```
CaptureAgent (SQL Server CDC capture)
  → InMemoryChangeBus (bounded queue, default 2000 events)
  → ReplicationChangeConsumer → ChangeApplier (parameterized UPSERT/DELETE)
       ├── Deduplicator (LRU; optional Redis backend)
       └── CheckpointStore (_replication_checkpoint on target PostgreSQL)
```

Optional external broker: set `REPLICATION_RABBITMQ_URL` to also consume via **aio-pika**. Stream lifecycle is tracked in metadata `replication_streams` with a 9-state FSM (`IDLE → STARTING → CDC_STREAMING → PAUSED → COMPLETED / FAILED`). **Pause**, **resume**, and **stop** preserve LSN/checkpoint position.

Platform-wide **CDC capture tuning** (poll interval and batch size) is persisted in `platform_replication_settings` and editable under **Settings → Replication**; active streams pick up changes immediately.

### Cutover & Migration Programs (Enterprise)

For staged rollouts and production cutover, the platform adds:

- **Migration programs** — `GET/POST /api/v1/programs` with waves, table lists, and sign-off (`require_feature("programs")`)
- **Cutover workflow** — `POST /api/v1/workflows/cutover/start` creates durable checkpoints in `cutover_checkpoints`; operators approve, commit, or rollback within a 24-hour window
- **Write freeze + connection switch** — `WriteFreezeService` and a connection-switch manifest guide DNS/connection-string cutover after validation passes

See [OPERATIONS.md](OPERATIONS.md) for runbooks and SLO targets.

---

## Application Pages & Features

The sidebar groups pages into three sections. Here is what each page does:

### Core Workflow

#### Dashboard — `/`

The default landing page. Shows a live overview that auto-refreshes every 10 seconds:

- **Stats row** — active migrations, completed jobs, failures, and project count with clickable links to filtered views
- **Recent Jobs** — last 5 migration jobs with status badge, table count, and inline progress bar; click any row to drill into job details
- **Projects sidebar** — quick links to assess each project
- **System Status** — API health badge, last sync time, and quick-action buttons to run an assessment or start a migration

#### Projects — `/projects`

Create and manage migration projects. Each project pairs a SQL Server source connection with a PostgreSQL target connection. Projects are the top-level organisational unit — assessments, migrations, and schema comparisons all hang off a project.

#### Assessment — `/assessment`

Database readiness report. Connect to a source, select a schema, and SQL Optima introspects `sys.`* catalog views to produce:

- Per-table classification: `SAFE` / `WARNING` / `BLOCKER`
- Complexity distribution chart
- Estimated migration time per table
- Downloadable JSON/Markdown assessment report
- **Executive report** — ROI estimate, license savings, risk score, projected timeline (`ExecutiveReportBuilder`)
- One-click launch into the Migration Center for tables that are ready

#### Migrations — `/migrations` and `/migrations/[jobId]`

Migration job management in two views:

- **New migration dialog** — discover tables, auto-run assessment, per-table tier badges and expandable concerns, then start migration
- **Job list** — filterable by status (running / completed / failed), derived status consistent with job detail
- **Job detail** — per-table progress bars, phase timeline (extract → transform → load), error log, pause/resume/cancel controls, and a link to the validation report once the job finishes

#### Validation — `/validation/[jobId]`

Per-job validation results for L1–L4 with pass/fail hero cards, aggregate-type grid for L2, error summaries, downloadable reports, and **Compare Sample Rows** (top 10 by PK).

#### Replication — `/replication`

CDC stream management backed by `/api/v1/replication/`*:

- **CDC preflight** — checks database- and table-level CDC before allowing **Create & start**
- **Create & start** streams from source/target connections and a selected table
- **Schema drift concerns** surfaced at create time (missing target table = blocker; column/PK mismatches = warnings)
- Live metrics: events captured, events applied, in-memory queue depth
- **Pause / resume / stop** without losing checkpoint position
- Stream list polls status every 5 s while active

---

### Analysis & Tools

#### Comparison — `/comparison`

Split-pane schema comparison between source and target. Both panes render the **comparison tree** (not raw inventories) with accurate match status: `EXACT`, `PARTIAL`, `SOURCE_ONLY`, `TARGET_ONLY`. Column nodes show source/target types; **Details** lists significant diffs (indexes, constraints, nullable/type changes). KPI cards reflect real matched/partial/source-only counts. **Def** opens DDL from both sides for a selected object.

#### Objects — `/objects` and `/discovery/[projectId]`

Discovered object browser. After running discovery on a project, this page lists every table, view, stored procedure, function, and trigger grouped by schema. Expandable tree with column details, data types, indexes, and foreign keys. Dependency graph view (powered by NetworkX on the backend) shows which objects must be migrated before others.

#### SQL Converter — `/sql`

Interactive T-SQL → PL/pgSQL playground:

- Paste any T-SQL snippet and click **Convert** to see the PL/pgSQL output side-by-side
- Syntax-highlighted diff shows exactly what changed
- Displays warnings for constructs that need manual review
- Useful for testing conversion rules before running a full migration

#### Reports — `/reports`

Reports hub that lists all completed migration jobs. For each job you can:

- Download a full Markdown assessment report
- Download a JSON data-quality report with per-table L1–L4 results
- View a summary of pass/fail counts inline

---

### Admin

#### Admin — `/admin`

Admin panel and API endpoints (ADMIN role unless noted):

- **User Management** — create, edit, disable, and delete users; assign roles (`admin` / `operator` / `viewer`)
- **Platform Settings** — configure global defaults such as default chunk size, max parallel workers, and retention policy for old job records
- **Audit log** — `GET /api/v1/admin/audit-log` with filters for action, actor, resource, and `project_id`
- **Metadata security audit** — `GET /api/v1/admin/metadata-security` reviews credential storage posture
- **Edition & usage** — `GET /api/v1/admin/edition` (current edition + features), `GET /api/v1/admin/usage` (rows migrated, jobs, logins over N days)
- **SLOs & capacity** — `GET /api/v1/admin/slos` publishes throughput, replication lag, and sizing guidance
- **Go engine health** — worker heartbeat from metadata DB
- **Alerts** — `GET /api/v1/alerts` aggregates platform alerts; webhook/email test via `POST /api/v1/alerts/test`

#### Settings — `/settings`

Platform configuration (admin and operator roles; viewers are redirected):

- **General** — API endpoint, theme, migration environment
- **Connections** — saved source/target connection profiles
- **Notifications** — webhook and SMTP alert delivery
- **Migration** — source throttle, table delays, max tables per job
- **Replication** — CDC poll interval and rows-per-chunk batch size (hot-reloads active streams)

#### Setup — `/setup`

First-time setup wizard. Shown automatically when no admin account exists. Guides you through creating the initial admin user with a password strength indicator and email validation. Redirects to the Dashboard on completion.

---

## Architecture Overview

```
Browser (Next.js 15 + React 19 + TailwindCSS v4)
        │
        ▼
FastAPI (Python 3.11) — control plane  ←→  Metadata DB (PostgreSQL)
        │                                      ▲
        │ dispatch / commands / progress       │ poll + write
        ▼                                      │
Go migration-engine (engine-go/) — data plane ─┘
        │
        ├── bbolt ChunkQueue (crash-safe chunk state)
        ├── planner (PK / date / UUID / adaptive sizer)
        ├── extractor (go-mssqldb → CellValue stream)
        └── loader (pgx binary COPY / UPSERT)
        │
        ├── AST Transpiler   (SQLGlot primary, ANTLR4 fallback)  [Python]
        ├── Discovery        (SQL Server sys.* catalog views)     [Python]
        ├── Validation       (L1–L4 parameterized queries)        [Python]
        ├── Replication      (capture → queue → apply, FSM)       [Python]
        └── Lineage          (NetworkX dependency graph)         [Python]
```


| Layer               | Stack                                                                                                       |
| ------------------- | ----------------------------------------------------------------------------------------------------------- |
| Frontend            | Next.js 15, React 19, TailwindCSS v4, shadcn/ui, TanStack Query                                             |
| Control plane       | Python 3.11, FastAPI, JWT auth (HS256)                                                                      |
| Data plane          | Go 1.23, `go-mssqldb`, `pgx/v5`, bbolt, OpenTelemetry                                                       |
| SQL Transpilation   | SQLGlot, ANTLR4                                                                                             |
| Database connectors | pyodbc (SQL Server, Python), asyncpg (PostgreSQL, Python)                                                   |
| Replication         | `CaptureAgent` → `InMemoryChangeBus` (default) or aio-pika/RabbitMQ; `ChangeApplier` + optional Redis dedup |
| Orchestration       | Temporal.io (optional — `/api/v1/workflows` for full migration + cutover)                                   |
| Observability       | Prometheus `/metrics`, `GET /admin/slos`, alert webhooks                                                    |
| Packaging           | Helm chart (`deploy/helm/sql-optima/`), product editions + HMAC license keys                                |
| Metadata store      | PostgreSQL (`postgres_checklist` container or `METADATA_DB_URL`)                                            |


---

## Configuration

`python start.py` auto-generates `.env` on first run. Edit it to point at your databases:

```ini
# Encryption & auth (auto-generated — do not share)
MIGRATION_MASTER_KEY=<generated>
MIGRATION_JWT_SECRET=<generated>

# SQL Server source
MIGRATION_SOURCE_HOST=localhost
MIGRATION_SOURCE_PORT=1433
MIGRATION_SOURCE_DATABASE=source_db
MIGRATION_SOURCE_USER=sa
MIGRATION_SOURCE_PASSWORD=

# PostgreSQL target
MIGRATION_TARGET_HOST=localhost
MIGRATION_TARGET_PORT=5432
MIGRATION_TARGET_DATABASE=target_db
MIGRATION_TARGET_USER=postgres
MIGRATION_TARGET_PASSWORD=

# Metadata database (auto-started via Docker if available)
METADATA_DB_URL=postgresql+asyncpg://postgres:postgres@localhost:5555/migration_checklist

# Go migration-engine (start.py sets these from METADATA_DB_URL if omitted)
MIGRATION_DATABASE_METADATA_URL=postgresql://postgres:postgres@localhost:5555/migration_checklist
MIGRATION_QUEUE_PATH=data/migration_queue.bbolt

# Replication (optional — in-process bus is used when RabbitMQ URL is unset)
REPLICATION_QUEUE_SIZE=2000
# REPLICATION_RABBITMQ_URL=amqp://guest:guest@localhost:5672/

# Product edition & licensing (see PACKAGING.md)
MIGRATION_EDITION=enterprise          # assess | migrate | replicate | enterprise
MIGRATION_LICENSE_KEY=DEV-LOCAL         # HMAC license token; DEV-LOCAL blocked when MIGRATION_ENV=production
# MIGRATION_LICENSE_SECRET=             # defaults to MIGRATION_MASTER_KEY

# Pre-migration snapshot gate
MIGRATION_SNAPSHOT_DIR=./snapshots
# MIGRATION_ALLOW_NO_SNAPSHOT=1         # dev-only — skip pg_dump requirement
```

---

## CLI Reference

SQL Optima is fully scriptable for DevOps integration:

```bash
# Convert a stored procedure
python -m apps.cli.main convert -i procedure.sql -o output.sql --type procedure --name usp_example

# Analyse T-SQL complexity
python -m apps.cli.main analyze -i proc.sql -o report.json

# Control-flow graph (Mermaid)
python -m apps.cli.main analyze-cfg -i proc.sql --format mermaid --output cfg.md

# Variable usage analysis
python -m apps.cli.main analyze-vars -i proc.sql --unused

# Discover schema objects
python -m apps.cli.main discover --connection-id <uuid> --schema dbo

# Run a migration
python -m apps.cli.main migrate --source-connection <uuid> --target-connection <uuid> --tables users orders

# Validate after migration
python -m apps.cli.main validate --source-connection <uuid> --target-connection <uuid> --tables users
```

Generate a JWT for direct API access:

```python
from apps.api.middleware.auth import create_token
print("Bearer", create_token("admin"))
```

### Replication API

```bash
# List streams
curl -H "Authorization: Bearer $TOKEN" http://localhost:8508/api/v1/replication/streams

# Check CDC status (optional preflight)
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8508/api/v1/replication/cdc-status?source_connection_id=<uuid>&source_schema=dbo&tables=Orders"

# Create a stream (CDC mode; requires CDC enabled on source)
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"orders-cdc","source_connection_id":"<uuid>","target_connection_id":"<uuid>","tables":["Orders"],"source_schema":"dbo","target_schema":"public"}' \
  http://localhost:8508/api/v1/replication/streams

# Start / pause / resume / stop
curl -X POST -H "Authorization: Bearer $TOKEN" http://localhost:8508/api/v1/replication/streams/<id>/start
curl -X POST -H "Authorization: Bearer $TOKEN" http://localhost:8508/api/v1/replication/streams/<id>/pause
curl -X POST -H "Authorization: Bearer $TOKEN" http://localhost:8508/api/v1/replication/streams/<id>/resume
curl -X POST -H "Authorization: Bearer $TOKEN" http://localhost:8508/api/v1/replication/streams/<id>/stop
```

---

## Development

```bash
# Run Python tests
python -m pytest tests/ -v

# Run Go engine tests (no live DB required)
cd engine-go && go test ./...

# Live Go integration test (requires SQL Server + PostgreSQL env vars)
cd engine-go && go test -tags integration -v ./internal/worker/... -run TestChunkPipeline

# Lint and format (Python)
ruff check .
ruff format .

# Type checking
mypy .

# Full Docker stack (SQL Server, PostgreSQL, Redis, RabbitMQ, Temporal, migration-engine, …)
docker compose up

# Kubernetes (Helm)
helm install sql-optima ./deploy/helm/sql-optima \
  --set env.MIGRATION_EDITION=enterprise
```

### Operator documentation


| Document                            | Contents                                                    |
| ----------------------------------- | ----------------------------------------------------------- |
| [ARCHITECTURE.md](ARCHITECTURE.md)  | Full system design and data flows                           |
| [OPERATIONS.md](OPERATIONS.md)      | Runbooks, SLOs, cutover checklist, live equivalence tests   |
| [PACKAGING.md](PACKAGING.md)        | Editions, license key generation, Helm deployment           |
| [RELEASE.md](RELEASE.md)            | Version history, upgrade notes, and release highlights      |
| [SECURITY.md](SECURITY.md)          | Production hardening, JWT rotation, metadata security audit |
| [CONTRIBUTING.md](CONTRIBUTING.md)  | Development setup, tests, and pull request guidelines       |


---

## Contributing

We welcome issues and pull requests. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, test commands, and PR expectations.

To report a security issue, follow [SECURITY.md](SECURITY.md) — please do **not** open a public GitHub issue for vulnerabilities.

---

## License

MIT License — see [LICENSE](LICENSE) for details.

© 2026 Ravi Sharma. Built with precision for the enterprise.