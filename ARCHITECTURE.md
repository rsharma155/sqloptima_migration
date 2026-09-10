# Architecture — SQL Server → PostgreSQL Migration Platform

**Repository:** [github.com/rsharma155/sqloptima_migration](https://github.com/rsharma155/sqloptima_migration)  
**Version:** 0.2.1 — Go data plane + control plane (programs, reports, project scoping, replication settings, Transfer schema clone)  
**Last updated:** 2026-09-09  
**Author:** Ravi Sharma  
**License:** MIT — © 2026 Ravi Sharma

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [High-Level Architecture](#2-high-level-architecture)
3. [Component Breakdown](#3-component-breakdown)
4. [Data Flows](#4-data-flows)
5. [Database Schema](#5-database-schema)
6. [Security Architecture](#6-security-architecture)
7. [API Layer Design](#7-api-layer-design)
8. [Domain Model](#8-domain-model)
9. [T-SQL → PL/pgSQL Transpilation Pipeline](#9-t-sql--plpgsql-transpilation-pipeline)
10. [Migration Data Pipeline](#10-migration-data-pipeline)
    - [Phased target DDL lifecycle](#phased-target-ddl-lifecycle)
    - [Post-migration finalize](#post-migration-finalize)
11. [Go Data Plane](#11-go-data-plane-engine-go)
12. [Replication Architecture (CDC)](#12-replication-architecture-cdc)
13. [Layer Dependencies](#13-layer-dependencies)
14. [Key Design Decisions](#14-key-design-decisions)
15. [Status Summary](#15-status-summary)

---

## 1. System Overview

The platform is a **compiler-style migration engine** that treats SQL Server → PostgreSQL migration as a translation problem:

```
Source (SQL Server)  →  Discovery + Assessment  →  Schema Conversion
                                                  ↓
                                          IR (Intermediate Representation)
                                                  ↓
                                         PL/pgSQL Generator
                                                  ↓
           Target (PostgreSQL)  ←  Data Migration Pipeline  ←  Validation
```

All SQL transformations operate on **AST nodes** — never on raw strings or regex patterns. All DDL identifiers (schema names, table names, column names) are wrapped in double-quotes via `quote_pg_ident()` before being embedded in any SQL string. These are the two most important architectural invariants.

The system is split into two planes:

- **Python Control Plane** — auth (incl. first-run `/auth/setup`), project management + **JWT project scoping**, discovery, assessment, schema conversion (parse unblockers + pgparse repair), validation, reporting, **replication (CDC)**, cutover/programs/waves, schema comparison, observability (`/metrics`, SLOs), licensing, REST API, Next.js UI
- **Go Data Plane** — chunk planner, bulk data extraction (`go-mssqldb` driver), bbolt persistent queue, PostgreSQL binary `COPY` loader, and CDC change-parsing/apply logic. All packages compile and test with no live database required.

Both planes communicate exclusively via the **PostgreSQL Metadata Repository** — no direct function calls, no REST calls between Go and Python.

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       Next.js UI  (port 3508)                           │
│         React 19 · TypeScript · TailwindCSS v4 · shadcn/ui             │
│         Typed client: api.ts — all paths under /api/v1                 │
│         Migration job detail + post-migration finalize dashboard       │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │ HTTPS REST /api/v1 + /api/comparison
┌──────────────────────────────────▼──────────────────────────────────────┐
│                  Python Control Plane  (FastAPI, port 8508)             │
│                                                                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────┐  │
│  │   Auth   │ │Connections│ │Assessment│ │Conversion│ │  Migration  │  │
│  │  /users  │ │/connections│ │ /assess  │ │ /convert │ │ /migrations │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └─────────────┘  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────┐  │
│  │Discovery │ │Validation│ │ Projects  │ │ Reports  │ │    Admin    │  │
│  │/discover │ │  /jobs   │ │ /projects │ │ /reports │ │   /admin    │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └─────────────┘  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────┐  │
│  │Replication│ │Comparison│  /api/v1/replication/* · /api/comparison  │
│  └──────────┘ └──────────┘                                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐                   │
│  │ Programs │ │ Workflows│ │  Alerts  │ │  /metrics│  cutover · Temporal│
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘                   │
│                                                                         │
│  Startup: init_db() → startup_checks() → load_connections() →         │
│           load_jobs() → bootstrap_admin()                              │
│                                                                         │
│  Middleware stack (outermost → innermost):                             │
│    CORS → LegacyRedirect(308) → Logging → Auth(JWT)                   │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │ SQLAlchemy async / psycopg3
┌──────────────────────────────────▼──────────────────────────────────────┐
│              PostgreSQL Metadata Repository  (port 5432)                │
│                                                                         │
│  Tables: auth_users · auth_sessions · project_connections              │
│          migration_jobs · migration_table_plans · migration_commands   │
│          validation_runs · validation_mismatches · project_projects    │
│          migration_quarantine · replication_streams                    │
│          audit_log · cutover_checkpoints · migration_programs/waves    │
│                                                                         │
│  (SQLite fallback for zero-config dev via METADATA_DB_URL)             │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │ Poll commands (500 ms) / LISTEN/NOTIFY
                                   │ Write chunk state, metrics, checkpoints
┌──────────────────────────────────▼──────────────────────────────────────┐
│                        Go Data Plane  (engine-go/)                      │
│                                                                         │
│  ┌───────────────┐  ┌──────────────────┐  ┌───────────────────────┐   │
│  │ planner       │  │  extractor       │  │    loader             │   │
│  │ PK / Date /   │  │ go-mssqldb       │  │ pg_binary COPY enc.   │   │
│  │ Adaptive sizer│─▶│ stream + schema  │─▶│ CellValue → COPY IN   │   │
│  └───────┬───────┘  └────────┬─────────┘  └──────────▲────────────┘  │
│          │                   │ []CellValue              │              │
│          │          ┌────────▼────────────────────────┐│   ┌────────┐ │
│          └─────────►│   queue: bbolt ChunkQueue        ├┘   │  cdc   │ │
│                     │   (embedded, crash-safe)         │    │ Lsn /  │ │
│                     └───────────────────────────────────┘    │ apply  │ │
│   core: shared types + type_mapping matrix                    └────────┘ │
└─────────────────────────┬───────────────────────────────────────────────┘
                          │                         │
              ┌───────────▼───────┐    ┌────────────▼──────────┐
              │  SQL Server       │    │  PostgreSQL (target)  │
              │  sys.* catalogs   │    │  binary COPY FROM     │
              │  cdc.*_CT tables  │    │  STDIN (pgx/v5)       │
              └───────────────────┘    └───────────────────────┘
```

---

## 3. Component Breakdown

### 3.1 Python Control Plane

#### API Layer (`apps/api/`)

Deliberately thin. Each router calls an application service — no business logic, no direct DB queries inside routers. All routes are mounted under `/api/v1`. A legacy-redirect middleware (308) handles old flat paths during the deprecation window.

| Router | Prefix | Responsibility |
|---|---|---|
| `auth_router.py` | `/api/v1/auth/*`, `/api/v1/users` | Login, token refresh, user CRUD |
| `connections_router.py` | `/api/v1/connections`, `/api/v1/create-database` | Connection profiles with encrypted passwords |
| `migrations_router.py` | `/api/v1/migrations/**` | Job lifecycle: start, pause, resume, stop, progress, **post-migration finalize** |
| `conversion_router.py` | `/api/v1/convert`, `/api/v1/sql/validate` | T-SQL → PL/pgSQL, syntax validation |
| `validation_router.py` | `/api/v1/jobs/{id}/validate`, `/api/v1/validation-runs` | L1–L4 validation with persistence |
| `discovery_router.py` | `/api/v1/discover`, `/api/v1/mapping` | Schema discovery, column type mapping |
| `assessment_router.py` | `/api/v1/assess` | SAFE/WARNING/BLOCKER assessment |
| `projects_router.py` | `/api/v1/projects` | Migration project CRUD |
| `reports_router.py` | `/api/v1/reports` | Migration + validation report downloads; executive summary |
| `admin_router.py` | `/api/v1/admin` | Job retention, ODBC check, diagnostics, audit log, metadata security, edition/usage/SLOs, Go engine health |
| `comparison_router.py` | `/api/comparison` | Side-by-side schema comparison (own prefix) |
| `replication_router.py` | `/api/v1/replication/streams/**` | Stream CRUD, start/stop/pause/resume, live status |
| `programs_router.py` | `/api/v1/programs/**` | Migration programs, waves, sign-off (Enterprise edition) |
| `workflow_router.py` | `/api/v1/workflows/**` | Temporal full migration + cutover workflow start/approve/commit |
| `alerts_router.py` | `/api/v1/alerts/**` | Platform alert aggregation, webhook/email config |

#### Application Services (`application/`)

| Service | Responsibility |
|---|---|
| `auth_service.py` | bcrypt password hashing, user CRUD, DB-backed sessions, bootstrap admin |
| `migration_service.py` | Job lifecycle control plane: dispatch to Go engine, pause/stop/resume via commands, metadata sync, completion watcher |
| `connection_service.py` | Connection CRUD with SecretsManager encrypt/decrypt |
| `validation_service.py` | L1–L4 orchestration, DB persistence, row-sample compare API, report export |
| `replication_service.py` | Stream CRUD, schema-drift concerns at create, lifecycle (start/stop/pause/resume), metrics sync |
| `replication_runtime.py` | In-process runtime: wires `CaptureAgent`, `InMemoryChangeBus`, `ReplicationChangeConsumer` |
| `reporting_service.py` | Migration and validation summary reports |
| `discovery_service.py` | Wraps `DiscoveryEngine` with connection resolution |
| `conversion_service.py` | Wraps `ProceduralConverter` with logging |
| `retention_service.py` | Scans `migration_jobs`, deletes/archives by age according to `RetentionPolicy` |
| `go_engine_migration/` | Go job dispatch JSON contract, command issue, **target table provisioning** (minimal load DDL), **deferred schema catalog**, **post-migration finalizer**, job watcher (validation + finalize + audit/alerts on terminal status) |
| `metadata_security_service.py` | Metadata DB credential storage audit (§12.8) |
| `alert_service.py` / `notification_service.py` | Platform alert collection and webhook/email delivery |
| `workflow_bridge_service.py` | Temporal workflow submission and status sync |

#### Startup Checks (`apps/api/startup_checks.py`)

Two checks run inside `startup()` immediately after `init_db()`:

| Check | Behaviour |
|---|---|
| `check_metadata_db()` | Runs `SELECT 1` via SQLAlchemy. **Hard failure** — `RuntimeError` if unreachable. |
| `check_odbc_driver()` | Reads `pyodbc.drivers()`. **Soft warning** — API continues if no SQL Server driver found (non-SQL-Server paths still work). |

#### Middleware (`apps/api/middleware/auth.py`)

- JWT verification on every request (except `PUBLIC_PATHS`)
- `PUBLIC_PATHS` = `/health`, `/health/deep`, `/metrics`, `/docs`, `/openapi.json`, `/redoc`, `/api/v1/auth/login|token|refresh|setup|setup-required` (plus legacy flat equivalents during deprecation window)
- `UserRole` enum: `VIEWER < OPERATOR < ADMIN`
- `require_role(minimum_role)` FastAPI dependency — reads role from JWT payload (no DB call)
- JWT may carry optional `project_id` for non-admin scoping (`shared/tenancy/project_scope.py`)
- `create_access_token` (8 h, `jti` claim) and `create_refresh_token` (7 d)

### 3.2 Domain Layer (`domains/`)

Pure Python — no I/O, no async, no database calls.

| Domain | Responsibility |
|---|---|
| `assessment/` | `AssessmentEngine` — SAFE/WARNING/BLOCKER rating, 0–100 complexity score, time estimate |
| `discovery/` | `DiscoveryEngine` — multi-schema discovery; `computed_column_discovery`, `index_discovery`, `synonym_discovery`, `pii_classifier` |
| `chunking/` | `ChunkPlanner`, `DateTimeChunkPlanner` — half-open `[start, end)` PK/datetime boundaries aligned with extract queries |
| `migration/` | `MigrationEngine` dispatch types, `ParallelMigration`, `LobStreamer`, `DryRunMigration`, `SnapshotGate`, `masking_discovery`, Go dispatch config; **`deferred_schema_catalog`** (identity/index/FK/check/default/trigger inventory); **`post_migration_ddl_generator`** + **`post_migration_finalize_models`** |
| `migration/retention_policy.py` | `RetentionPolicy` value object — max_age_days, keep_failed flag, action (DELETE/ARCHIVE) |
| `transpilation/` | AST pipeline: parser → IR → transformation rules → PL/pgSQL generator |
| `transpilation/repair/` | `ConversionRepairService` — validate → fix → re-validate loop via pgparse + rule-based fixers |
| `transpilation/ddl_generator.py` | All DDL identifiers quoted via `quote_pg_ident()` — no raw identifier embedding |
| `transpilation/schema_mapper.py` | `SchemaMapper.apply()` — word-boundary regex substitution for schema relabelling |
| `validation/` | `ValidationEngine`, L3/L4 validators, `PostgresSyntaxValidator`, query/procedure equivalence harnesses, `RowHashValidator` |
| `lineage/` | NetworkX DAG, topological sort, SCC detection for circular dependency resolution |
| `parsing/` | `SqlglotParser` (primary), `AntlrAdapter` (fallback), `TsqlParseUnblocker`, `ResilientTranspiler` |
| `reporting/` | Markdown/JSON assessment reports; `ExecutiveReportBuilder` (ROI, risk score, timeline) |
| `comparison/` | Side-by-side schema comparison (`ComparisonEngine`, `significant_diffs` for EXACT vs PARTIAL) |
| `replication/` | `schema_drift_detector`, `cdc_requirements`, `validators` (SQL identifier safety), stream entities |
| `orchestration/` | Temporal workflows/activities; `CutoverService`, `WriteFreezeService`, `ConnectionSwitchManifest` |
| `licensing/` | `editions.py` feature gates, `license_enforcement.py` HMAC validation |
| `observability/` | In-memory metrics, `prometheus_exporter`, `UsageMeteringService`, published SLO targets |

### 3.3 Infrastructure Layer (`infrastructure/`)

| Adapter | Technology | Purpose |
|---|---|---|
| `metadata_db/` | SQLAlchemy 2 async + aiosqlite/asyncpg | Platform state repository |
| `sqlserver/` | pyodbc (wrapped in `asyncio.get_running_loop().run_in_executor()`) | SQL Server connection + `sys.*` discovery |
| `postgres/` | asyncpg connection pool | PostgreSQL connection + `information_schema` discovery; all DDL identifiers via `quote_pg_ident()`; **`postgres_table_ddl.py`** reconstructs readable CREATE TABLE DDL without duplicate PK/index statements |
| `ai/` | OpenAI / Anthropic / local LLMs | Advisory analysis only — never executes migration |
| `temporal/` | Temporal.io SDK | Durable workflow execution |
| `replication/` | `InMemoryChangeBus`, `LoopbackPublisher`, `ReplicationChangeConsumer`, `SqlServerWatermarkAdapter` | Capture → queue → apply pipeline |
| `redis/` | Redis client | Optional replication dedup backend (scoped `SCAN`/`DEL`, never `flushdb`) |
| `sql_scripts/` | Privilege / script catalog | Least-privilege grant scripts and related SQL assets |
| `metadata_db/repositories/replication_stream_repository.py` | SQLAlchemy async | `replication_streams` CRUD + status/metrics updates |

### 3.4 Shared Kernel (`shared/`)

Zero dependencies on outer layers.

| Module | Purpose |
|---|---|
| `kernel/database_object.py` | `DatabaseObject`, `Table`, `Column`, `DataType` — canonical domain types |
| `kernel/ddl_identifier.py` | `quote_pg_ident(name)` — double-quotes + inner `"` escaping; `DdlIdentifier` value object; `validate_sql_identifier()` (empty/63-char limits) |
| `security/secrets_manager.py` | Fernet + PBKDF2 600k rounds; `encrypt()` (legacy); `encrypt_v2(key_id)` → `v2:key_id:salt:token`; `decrypt_auto()` handles all formats; `rotate()` batch re-encryption |
| `logging/structured_logging.py` | structlog + OpenTelemetry configuration |
| `contracts/base_connector.py` | Port interfaces for DB connectors and discovery |
| `contracts/replication_ports.py` | `ChangePublisherPort`, `ChangeConsumerPort`, `ReplicationStreamRepositoryPort` |
| `tenancy/project_scope.py` | `resolve_project_filter`, `assert_resource_project_access`, `connection_in_project` — pin non-admin JWTs to a project; admins remain unscoped |
| `errors/`, `events/`, `utils/` | Platform error catalog, migration events, shared helpers |

---

## 4. Data Flows

### 4.1 Authentication Flow

```
Client
  │
  ├─► POST /api/v1/auth/login {username, password}
  │         │
  │         ├─ AuthService.authenticate()
  │         │    ├─ bcrypt.checkpw(password, stored_hash)  [constant time — _DUMMY_HASH for missing users]
  │         │    └─ record_login()
  │         │
  │         └─ Returns {access_token (8h), refresh_token (7d)}
  │                    │                        │
  │                    │                   stored as sha256(token) in auth_sessions
  │
  └─► POST /api/v1/auth/refresh {refresh_token}
            │
            ├─ verify_refresh_token() [JWT signature + typ="refresh" claim check]
            ├─ AuthService.validate_refresh_session() [DB lookup by sha256 hash]
            ├─ revoke old session
            └─ Returns new {access_token, refresh_token}
```

### 4.2 Migration Job Flow

```
POST /api/v1/migrations {source_conn, target_conn, tables[], masking_policy, require_target_snapshot, …}
  │
  ├─ require_valid_license() + require_feature("migration")
  │
  ├─ MigrationService.start_migration()
  │    ├─ SnapshotGate.verify_or_create() if require_target_snapshot (pg_dump ref)
  │    ├─ masking_discovery + column_transforms when masking_policy auto|strict
  │    ├─ Creates MigrationJob (executor=go, in-memory registry + metadata DB)
  │    ├─ asyncio.create_task(_dispatch_go_migration_job(job_id))
  │    └─ Returns job to client (status PENDING → QUEUED after dispatch)
  │
  ├─ _dispatch_go_migration_job (Python control plane)
  │    ├─ GoMigrationJobDispatcher.dispatch()
  │    │    ├─ DeferredSchemaCatalogBuilder — discover identity, secondary indexes, FKs,
  │    │    │   checks, defaults, triggers from SQL Server sys.* (stored in plan_config)
  │    │    ├─ provision_target_tables() — minimal-load CREATE TABLE (columns + PK only)
  │    │    ├─ Builds JSON config (tables, chunk_size, parallel_workers, masking, idempotent, …)
  │    │    ├─ Persists migration_jobs.config + migration_table_plans rows
  │    │    └─ Sets job status QUEUED for Go worker claim
  │    └─ asyncio.create_task(watch_go_migration_job())
  │         └─ Polls metadata until terminal status
  │            ├─ L1 validate_table on COMPLETED (row-count parity)
  │            ├─ PostMigrationFinalizer on COMPLETED + validation pass (optional)
  │            └─ Audit + notification hooks
  │
  │  [Go migration-engine — data plane]
  │    ├─ MigrationJobClaimer polls metadata, claims QUEUED job
  │    ├─ MigrationGoJobHandler.Run()
  │    │    ├─ LISTEN/NOTIFY + CommandPoller for PAUSE/STOP/RESUME
  │    │    ├─ Decrypt connection credentials (MIGRATION_MASTER_KEY)
  │    │    └─ For each table:
  │    │         ├─ ResolveTableChunks (PK / datetime / UUID / composite PK)
  │    │         ├─ ensureTableChunksEnqueued → bbolt ChunkQueue
  │    │         ├─ Claim PENDING chunks → extract (go-mssqldb) → transform (PII masking)
  │    │         ├─ load (pgx binary COPY or UPSERT), AdaptiveChunkSizer.NextSize()
  │    │         ├─ retry [0,30,120]s; quarantine exhausted chunks
  │    │         └─ UpdateTablePlanProgress + job logs in metadata DB
  │    └─ SetMigrationJobStatus(completed|failed)
  │
GET /api/v1/migrations/{id}/progress
  └─ Reads job + table_plans from metadata DB (written by Go worker)

GET /api/v1/migrations/{id}/post-migration
  └─ Deferred object inventory + per-object finalize status (from migration_jobs.config)

POST /api/v1/migrations/{id}/post-migration/finalize
  └─ Apply identity, indexes, FKs, checks, defaults (requires COMPLETED job)
```

### 4.2.1 Post-migration finalize flow

```
Migration COMPLETED + L1 validation passed
  │
  ├─ watch_go_migration_job() → _run_post_migration_finalize()  [if finalize_after=true]
  │    └─ PostMigrationFinalizer.finalize_table() per table (ordered steps below)
  │
  └─ Or operator triggers manually:
       POST /api/v1/migrations/{id}/post-migration/finalize {finalize_identities, …}
            │
            └─ UI: /migrations/{jobId}/post-migration

Per table (PostMigrationFinalizer):
  1. Identity columns  → ALTER COLUMN … ADD GENERATED BY DEFAULT AS IDENTITY + setval()
  2. Secondary indexes → CREATE INDEX [CONCURRENTLY] (PK / columnstore / spatial skipped)
  3. Foreign keys      → ADD CONSTRAINT … NOT VALID → VALIDATE CONSTRAINT
  4. Check constraints → ADD CONSTRAINT … CHECK … NOT VALID → VALIDATE CONSTRAINT
  5. Column defaults   → ALTER COLUMN … SET DEFAULT (transpiled expressions)
  6. Triggers          → skipped by default (manual review; finalize_triggers=false)

State persisted in migration_jobs.config.post_migration_finalize
  { status, tables: { table: { category: { object_key: applied|failed|… } } } }
```

### 4.3 Schema Conversion Flow

```
POST /api/v1/convert {sql, object_type, object_name, schema, parameters}
  │
  ├─ ConversionService.convert(req)
  │    │
  │    ├─ TsqlParseUnblocker.apply()     [upstream — GO, SET lines, hints, bracket idents]
  │    │
  │    ├─ ProceduralConverter.convert_procedure() (or function/trigger/auto)
  │    │    │
  │    │    ├─ _strip_ddl_wrapper()
  │    │
  │    ├─ TsqlPatternConverter.preprocess():
  │    │    ├─ _remove_nolock()           WITH (NOLOCK) → comment
  │    │    ├─ _flag_global_temp_tables() ##name → tmp_name + warning
  │    │    ├─ _convert_raiserror()       RAISERROR / THROW → RAISE EXCEPTION
  │    │    └─ _convert_output_clause()   OUTPUT INSERTED.col → RETURNING col
  │    │
  │    ├─ SqlglotParser.transpile()       [core AST transpilation — T-SQL → PostgreSQL SQL]
  │    │
  │    ├─ TsqlPatternConverter.postprocess():
  │    │    ├─ _convert_for_xml_path()    FOR XML PATH → annotation
  │    │    ├─ _convert_maxrecursion()    OPTION(MAXRECURSION n) → SET LOCAL comment
  │    │    └─ _convert_merge()           MERGE → INSERT ON CONFLICT / annotation
  │    │
  │    ├─ TsqlExpressionConverter: ISNULL→COALESCE, GETDATE→CURRENT_TIMESTAMP, etc.
  │    │
  │    └─ SchemaMapper.apply()            dbo.xxx → public.xxx (configurable)
  │    │
  │    ├─ ConversionRepairService.repair()  [pgparse validate → fixers → re-validate, ≤3 rounds]
  │    └─ PostgresSyntaxValidator.validate() on final SQL
  │
  └─ Returns {converted_sql, success, warnings[], errors[], parse_unblockers_applied[],
              repairs_applied[], postgres_syntax_valid, manual_review_required}
```

### 4.4 Replication Stream Flow

```
POST /api/v1/replication/streams {name, source_connection_id, target_connection_id, tables[], …}
  │
  ├─ ReplicationService.create_stream()
  │    ├─ validate_identifier() / validate_table_list()   [SQL injection guard]
  │    ├─ detect_schema_drift() per table → concerns_json (blocker/warning/info)
  │    └─ ReplicationStreamRepository.create() → replication_streams row (status IDLE)
  │
POST /api/v1/replication/streams/{id}/start
  │
  ├─ ReplicationService.start_stream()
  │    ├─ Reject if concerns contain blockers (e.g. target table missing)
  │    ├─ SqlServerWatermarkAdapter — parameterized TOP/watermark poll on source
  │    ├─ asyncpg connection to target (password via SecretsManager)
  │    └─ ReplicationRuntimeManager.start_stream()
  │         ├─ StateMachine: IDLE → STARTING → CDC_STREAMING
  │         ├─ InMemoryChangeBus (bounded, REPLICATION_QUEUE_SIZE default 2000)
  │         ├─ LoopbackPublisher → bus.publish(ChangeEvent)
  │         ├─ bus.start(ReplicationChangeConsumer.handle)
  │         ├─ CaptureAgent.start(schema, table_names=[…])  [per-table poll loops]
  │         └─ Optional RabbitMqBridgeConsumer if REPLICATION_RABBITMQ_URL set
  │
  [Per change event]
  CaptureAgent._capture_and_publish()
    └─ ChangeApplier.apply() on target PostgreSQL
         ├─ DedupKey.for_event() → Deduplicator (LRU; optional Redis)
         ├─ Parameterized INSERT … ON CONFLICT / DELETE
         └─ CheckpointStore.save() → _replication_checkpoint (target DB)
  │
POST …/pause | …/resume | …/stop
  └─ CaptureAgent.pause()/resume()/stop() + FSM transition + metadata status update

GET /api/v1/replication/streams/{id}/status
  └─ Merges DB record + runtime metrics (events_captured, events_applied, queue_depth)

API shutdown
  └─ replication_service.stop_all_streams() — graceful stop of all active runtimes
```

### 4.5 Cutover Workflow

```
POST /api/v1/workflows/cutover/start {source, target, tables[], snapshot_ref?, require_human_approval}
  │
  ├─ SnapshotGate.verify_or_create() — target pg_dump snapshot (unless snapshot_ref supplied)
  ├─ WriteFreezeService — record writes_frozen_at on source (operator signal)
  ├─ Final delta migration job (optional) + L1–L4 validation
  ├─ CutoverService.save_checkpoint() → cutover_checkpoints row (committed=false)
  │
POST /api/v1/workflows/cutover/{job_id}/approve
  └─ Human sign-off gate when require_human_approval=true

POST /api/v1/workflows/cutover/{job_id}/commit
  ├─ CutoverService.commit() — mark checkpoint committed, close 24h rollback window
  └─ ConnectionSwitchManifest — DNS/connection-string cutover checklist for operators

POST /api/v1/workflows/cutover/{job_id}/rollback
  └─ CutoverService.rollback() — truncate target tables listed in checkpoint
```

### 4.6 Migration Program Flow

```
POST /api/v1/programs {project_id, name}
  └─ migration_programs row (require_feature("programs"))

POST /api/v1/programs/{id}/waves {name, tables[], schema_name}
  └─ migration_waves row — ordered wave with sign-off state

POST /api/v1/programs/waves/{wave_id}/sign-off {approver}
  └─ Wave status → signed_off; unlocks linked migration job start
```

### 4.7 Secrets Rotation Flow

```
Existing ciphertexts (format: base64(salt):fernet_token — "legacy v1")

  SecretsManager(old_key).rotate(ciphertexts, new_master_key=new_key)
    │
    ├─ For each ciphertext:
    │    ├─ decrypt_auto(ct)          [handles legacy, v1:, v2: prefixes automatically]
    │    │    └─ plaintext
    │    └─ new_sm.encrypt_v2(plaintext, key_id="current")
    │         └─ "v2:current:base64(salt):fernet_token"
    │
    └─ Returns new_ciphertexts[]      [all in v2 format, decryptable only with new_key]

  Caller persists new_ciphertexts → ConnectionRepository.update(connection_id, encrypted_password=…)
  Caller switches to SecretsManager(new_key) for all future operations
```

---

## 5. Database Schema

### Metadata Repository Tables

All platform state lives in a single database (PostgreSQL in production, SQLite for dev). The schema uses flat table names (no PostgreSQL schemas) for SQLite compatibility.

#### `auth_users`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `email` | VARCHAR(255) | Unique |
| `username` | VARCHAR(100) | Unique |
| `password_hash` | VARCHAR(512) | bcrypt, 12 rounds |
| `role` | VARCHAR(20) | viewer / operator / admin |
| `is_active` | BOOLEAN | Deactivated users cannot log in |
| `created_at` | TIMESTAMPTZ | |
| `last_login_at` | TIMESTAMPTZ | Updated on every successful auth |

#### `auth_sessions`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `user_id` | UUID → `auth_users` | CASCADE delete |
| `refresh_token_hash` | VARCHAR(512) | sha256 hex of the raw JWT — never stored in plaintext |
| `expires_at` | TIMESTAMPTZ | 7 days from issuance |
| `created_at` | TIMESTAMPTZ | |

#### `project_connections`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `name` | VARCHAR(255) | Human-readable label |
| `db_type` | VARCHAR(20) | sqlserver / postgresql |
| `host` / `port` / `database_name` / `username` | — | Connection coordinates |
| `encrypted_password` | TEXT | `SecretsManager.encrypt_v2()` output — format: `v2:key_id:base64(salt):fernet_token` |
| `last_tested_at` | TIMESTAMPTZ | Set by `/api/v1/connections/{id}/test` |
| `last_test_ok` | BOOLEAN | |

#### `migration_jobs`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `source_connection_id` / `target_connection_id` | UUID → connections | SET NULL on delete |
| `status` | VARCHAR(20) | PENDING / RUNNING / PAUSED / STOPPED / COMPLETED / FAILED |
| `rows_total` / `rows_migrated` | BIGINT | |
| `tables_total` / `tables_done` | INTEGER | |
| `started_at` / `completed_at` | TIMESTAMPTZ | |
| `config` | JSON | Go dispatch JSON + **`finalize_options`** + **`post_migration_finalize`** state |

#### `migration_table_plans`
One row per table per job. Status transitions: `pending → running → completed | failed | stopped`. Tracks extraction strategy, row range, and per-table progress. **`plan_config`** JSON holds column transforms/types and **`deferred_schema`** — the post-migration object inventory captured at dispatch from SQL Server (`DeferredSchemaCatalogBuilder`).

#### `migration_commands`
One row per job. Written by the Python API (pause/resume/stop); read by the Go engine. `acked_at` is set by the Go engine when the command is acted upon.

#### `validation_runs` / `validation_mismatches`
Validation results per job per level (L1–L4). L3 stores chunk-level hash mismatches; L4 stores sampled row-level field mismatches.

#### `project_projects`
Migration project records linking a source connection, a target connection, and a human label. FK to `project_connections` (SET NULL on delete).

#### `migration_quarantine`
Rows that failed during migration (type conversion errors, constraint violations). FK to `migration_jobs` (CASCADE delete).

#### `replication_streams` *(Alembic 003 + 010)*
| Column | Type | Notes |
|---|---|---|
| `replication_stream_id` | VARCHAR(36) | PK |
| `project_connection_id` | VARCHAR(36) → `project_connections` | Source connection; SET NULL on delete |
| `target_project_connection_id` | VARCHAR(36) | Target PostgreSQL connection |
| `stream_name` | VARCHAR(255) | Human-readable label |
| `status` | VARCHAR(32) | 9-state machine: IDLE / STARTING / SNAPSHOTTING / CDC_CATCHUP / CDC_STREAMING / PAUSED / STOPPING / FAILED / COMPLETED |
| `config_json` | JSON | `source_schema`, `target_schema`, `tables[]`, `mode` (watermark/cdc) |
| `concerns_json` | JSON | Schema drift + operational warnings at create time |
| `events_captured` / `events_applied` | INTEGER | Runtime counters synced from `ReplicationRuntimeManager` |
| `last_checkpoint_lsn` | VARCHAR(64) | Mirror of target DB `_replication_checkpoint` for dashboard visibility |
| `error_message` | TEXT | Populated on FAILED |
| `started_at` / `stopped_at` | TIMESTAMPTZ | |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

#### `cutover_checkpoints`
Durable cutover state for rollback. Tracks `migration_job_id`, table list, LSN/row counts, `snapshot_ref`, `committed` flag, and optional `connection_switch` manifest JSON. Uncommitted checkpoints older than 24 h trigger SLO alerts.

#### `migration_programs` / `migration_waves`
Program-level migration planning. Programs link to `project_projects`; waves hold ordered table lists, sign-off metadata (`approver`, `signed_off_at`), and optional linked `migration_job_id`.

#### `audit_log`
Append-only audit trail for compliance: login events, migration start/stop, cutover commit/rollback. Filterable by `project_id` via `GET /api/v1/admin/audit-log`.

---

## 6. Security Architecture

### Authentication

```
Client request
    │
    ▼
LegacyRedirectMiddleware      (flat path? → 308 to /api/v1/…)
    │
    ▼
AuthMiddleware.dispatch()
    │
    ├─ Is path in PUBLIC_PATHS?
    │    /health, /docs, /openapi.json, /redoc,
    │    /api/v1/auth/login|token|refresh
    │    └─ Yes → pass through
    │
    ├─ Extract Bearer token from Authorization header
    │    └─ Missing or wrong scheme → 401
    │
    ├─ verify_token(token)
    │    ├─ jwt.decode(HS256 + MIGRATION_JWT_SECRET)
    │    ├─ ExpiredSignatureError → 401 Token expired
    │    └─ InvalidTokenError → 401 Invalid token
    │
    └─ request.state.user = {sub, role, typ, jti, exp}

Route handler
    └─ require_role(UserRole.OPERATOR)
         ├─ get_current_user(request) → payload from request.state
         ├─ UserRole(payload["role"]).has_permission(OPERATOR)
         │    └─ False → 403
         └─ True → handler executes
```

### Password security

- `bcrypt.hashpw(password, gensalt(rounds=12))` — ~100 ms deliberate delay
- Timing-safe: `_DUMMY_HASH` (a pre-computed valid bcrypt hash) is always checked for missing users to prevent user-existence oracle attacks
- Refresh tokens stored as `sha256(raw_jwt_string)` in `auth_sessions` — a breach of the session table yields only unusable hashes

### Data-at-rest encryption

Connection passwords are encrypted before any persistence. Two supported formats:

```
Legacy (v1):
  plaintext → encrypt(plaintext)
                ├─ random 16-byte salt
                ├─ PBKDF2(MIGRATION_MASTER_KEY, salt, 600_000 rounds, SHA-256)
                └─ base64(salt) + ":" + fernet_token

Versioned (v2, preferred for new writes):
  plaintext → encrypt_v2(plaintext, key_id="current")
                ├─ random 16-byte salt
                ├─ PBKDF2(MIGRATION_MASTER_KEY, salt, 600_000 rounds, SHA-256)
                └─ "v2:" + key_id + ":" + base64(salt) + ":" + fernet_token

Key rotation:
  SecretsManager(old_key).rotate([ct1, ct2, ...], new_master_key)
    ├─ decrypt_auto(ct) for each  [handles both legacy and v2]
    └─ new_sm.encrypt_v2(plaintext) for each  [all output in v2 format]
```

### DDL identifier safety

All SQL identifiers embedded in generated DDL go through `quote_pg_ident()` from `shared/kernel/ddl_identifier.py`:

```python
def quote_pg_ident(name: str) -> str:
    """Wrap name in PostgreSQL double-quotes; escape inner " by doubling."""
    if not name:
        raise ValueError("Cannot quote an empty identifier")
    return '"' + name.replace('"', '""') + '"'
```

This prevents both injection and case-sensitivity issues. The `DdlIdentifier` value object enforces this at construction time. The fix closes the gap in the old `_quote_ident` method which did not escape inner double-quotes.

### SQL injection prevention

Three layers:

1. **Identifier whitelist** in `DataExtractor`: schema, table, and column names validated against `^[a-zA-Z_][a-zA-Z0-9_ -]{0,127}$`
2. **DDL identifier quoting**: all DDL-embedded identifiers go through `quote_pg_ident()` — inner `"` are doubled, making injection impossible
3. **Parameterized queries**: all `WHERE` clauses and `VALUES` use `$1, $2, ...` with asyncpg or pyodbc parameter binding — never f-string SQL

---

## 7. API Layer Design

### Request lifecycle

```
Client → CORS middleware
       → LegacyRedirectMiddleware  [flat path → 308 to /api/v1/…]
       → LoggingMiddleware          [structured request/response logging with correlation_id]
       → AuthMiddleware             [JWT verify → request.state.user]
       → slowapi rate limiter       [200 req/min default; 60/min on /convert + login]
       → FastAPI router dispatch    [/api/v1/* prefix]
       → Route function             [calls application service only]
       → Application service        [domain logic + repository calls]
       → Repository                 [SQLAlchemy async session]
       → PostgreSQL / SQLite
```

### Error response format

All errors return JSON with a single `detail` field:

```json
{"detail": "Human-readable error message"}
```

| Status | Meaning |
|---|---|
| `308` | Legacy flat path — follow the `Location` header to `/api/v1/…` |
| `400` | Invalid input (e.g. invalid database name pattern) |
| `401` | Missing, expired, or tampered JWT |
| `403` | Valid JWT but insufficient role |
| `404` | Resource not found |
| `409` | Conflict (duplicate username/email) |
| `422` | Request body validation failure (Pydantic) |
| `502` | Upstream DB error (SQL Server / PostgreSQL unreachable) |

### Rate limiting

`slowapi` (required dependency) is wired on startup:

- Global default: `200/minute` per IP
- `POST /api/v1/convert`: explicit `60/minute` (prevents CPU exhaustion from large AST parses)
- `POST /api/v1/auth/login`: explicit `60/minute` (brute-force mitigation)

---

## 8. Domain Model

### Core types (`shared/kernel/database_object.py`)

```
DatabaseObject
  ├── database_name: str
  ├── schema_name: str
  ├── object_name: str
  ├── object_type: DatabaseObjectType (TABLE/VIEW/PROCEDURE/FUNCTION/TRIGGER/...)
  └── source_definition: str | None

Table(DatabaseObject)
  ├── row_count_estimate: int
  ├── is_temporal: bool
  ├── is_memory_optimized: bool
  ├── columns: list[Column]
  └── index_count: int

Column
  ├── column_name: str
  ├── data_type: DataType
  ├── is_identity: bool
  ├── is_computed: bool
  ├── is_nullable: bool
  └── collation_name: str | None
```

### DDL identifier (`shared/kernel/ddl_identifier.py`)

```
quote_pg_ident(name: str) -> str
  ├── Raises ValueError for empty string
  └── Returns '"' + name.replace('"', '""') + '"'

validate_sql_identifier(name: str, label: str) -> None
  ├── Raises ValueError for empty string
  └── Raises ValueError if len(name) > 63  [PostgreSQL NAMEDATALEN-1]

DdlIdentifier (frozen dataclass)
  ├── name: str              [validated at __post_init__]
  ├── quoted: str            [property → quote_pg_ident(self.name)]
  ├── __str__: str           [returns raw name]
  └── hashable               [usable in sets and as dict keys]
```

### Assessment domain (`domains/assessment/assessment_engine.py`)

```
TableAssessment
  ├── table_name, schema_name: str
  ├── migration_tier: MigrationTier (SAFE / WARNING / BLOCKER)
  ├── complexity_score: int (0–100)
  ├── estimated_minutes: float
  ├── lob_columns: list[str]
  ├── ci_collation_columns: list[str]
  ├── blocker_types: list[str]
  ├── blockers / warnings / prerequisites: list[str]
  └── row_count_estimate: int

DatabaseAssessment
  ├── database_name: str
  ├── tables: list[TableAssessment]
  ├── overall_tier: MigrationTier
  ├── safe_count / warning_count / blocker_count: int
  ├── estimated_total_minutes: float
  ├── cdc_enabled_db: bool
  ├── linked_server_refs / global_temp_table_refs / agent_jobs: list[dict]
  └── global_prerequisites: list[str]
```

---

## 9. T-SQL → PL/pgSQL Transpilation Pipeline

A **multi-pass compiler** that transforms T-SQL to PL/pgSQL without ever using regex on complete SQL text (only for specific, bounded sub-patterns after AST extraction).

```
Input T-SQL
     │
     ▼  TsqlParseUnblocker.apply()           [UPSTREAM NORMALIZATION]
     │  Strip GO, session SET lines, bracket identifiers, table hints, proc options
     ▼  ProceduralConverter._strip_ddl_wrapper()
     │  Extracts inner body from CREATE PROC/FUNCTION/TRIGGER...AS BEGIN...END
     ▼
TsqlPatternConverter.preprocess()          [BEFORE SQLGlot]
     │  ├─ _remove_nolock()                WITH (NOLOCK) → comment + warning
     │  ├─ _flag_global_temp_tables()      ##name → tmp_name + warning
     │  ├─ _convert_raiserror()            RAISERROR / THROW → RAISE EXCEPTION
     │  └─ _convert_output_clause()        OUTPUT INSERTED./DELETED. → RETURNING
     ▼
SqlglotParser.transpile()                  [CORE AST TRANSPILATION]
     │  Handles: TOP→LIMIT, CROSS/OUTER APPLY→LATERAL, CTEs, window functions,
     │           date functions, string functions, type casts, subqueries
     ▼
TsqlPatternConverter.postprocess()         [AFTER SQLGlot]
     │  ├─ _convert_for_xml_path()         FOR XML PATH → annotation
     │  ├─ _convert_maxrecursion()         OPTION(MAXRECURSION n) → SET LOCAL comment
     │  └─ _convert_merge()               MERGE → INSERT ON CONFLICT / annotation
     ▼
TsqlExpressionConverter.convert_expression()
     │  ├─ ISNULL(a,b)  → COALESCE(a,b)
     │  ├─ GETDATE()    → CURRENT_TIMESTAMP
     │  ├─ NEWID()      → gen_random_uuid()
     │  ├─ @@ROWCOUNT   → GET DIAGNOSTICS (with comment)
     │  └─ @@IDENTITY   → LASTVAL()
     ▼
SchemaMapper.apply()                       [SCHEMA RELABELLING]
     │  dbo.table → public.table  (word-boundary regex on schema prefix only)
     │  configurable via SchemaMappingConfig
     ▼
ConversionRepairService.repair()           [POST-CONVERSION REPAIR]
     │  PostgresSyntaxValidator (pgparse) → targeted pg_syntax_fixers → re-validate (≤3 rounds)
     ▼
ConversionResult {converted_sql, success, warnings[], errors[], parse_unblockers_applied[],
                  repairs_applied[], postgres_syntax_valid, manual_review_required}
```

### Auto-converted constructs

| T-SQL | PostgreSQL | Handler |
|---|---|---|
| `WITH (NOLOCK)` | `/* ⚠️ NOLOCK removed */` | `_remove_nolock` |
| `##temp_table` | `tmp_temp_table` + warning | `_flag_global_temp_tables` |
| `RAISERROR('msg', 16, 1)` | `RAISE EXCEPTION 'msg';` | `_convert_raiserror` |
| `THROW 51000, 'msg', 1` | `RAISE EXCEPTION 'msg';` | `_convert_raiserror` |
| `THROW;` (re-throw) | `RAISE;` | `_convert_raiserror` |
| `OUTPUT INSERTED.col` | `RETURNING col` | `_convert_output_clause` |
| `MERGE … WHEN MATCHED … WHEN NOT MATCHED` | `INSERT … ON CONFLICT DO UPDATE` | `_convert_merge` |
| `OPTION (MAXRECURSION n)` | `SET LOCAL max_recursion_depth = n` comment | `_convert_maxrecursion` |
| `TOP(n)` | `LIMIT n` | SQLGlot |
| `CROSS APPLY fn()` | `CROSS JOIN LATERAL fn()` | SQLGlot |
| `ISNULL(a, b)` | `COALESCE(a, b)` | `TsqlExpressionConverter` |
| `GETDATE()` | `CURRENT_TIMESTAMP` | `TsqlExpressionConverter` |
| `dbo.` prefix | `public.` (configurable) | `SchemaMapper` |

### Constructs requiring manual review (annotated, not silently dropped)

| Construct | Annotation |
|---|---|
| Complex `MERGE` | `⚠️ MANUAL REVIEW REQUIRED: MERGE statement` |
| `FOR XML PATH` | `⚠️ MANUAL REVIEW REQUIRED: rewrite using STRING_AGG()` |
| `OUTPUT INTO @table_var` | `⚠️ MANUAL REVIEW REQUIRED: OUTPUT INTO` |
| `##` global temp tables | `⚠️ MANUAL REVIEW REQUIRED: no PostgreSQL equivalent` |

---

## 10. Migration Data Pipeline

### Control plane (Python)

Python **does not** move row data in-process. `MigrationService` creates jobs, dispatches JSON config to metadata PostgreSQL, issues pause/stop/resume commands, and watches completion. Domain types (`ChunkedMigration`, `DataExtractor`, etc.) remain for unit tests and orchestration activities.

### Data plane (Go — production path)

```
POST /api/v1/migrations
    │
    └─ Python: INSERT migration_jobs + migration_table_plans (QUEUED)
             INSERT migration_commands (optional PAUSE/STOP)
             │
             ▼
Go migration-engine (cmd/migration-engine)
    │
    ├─ Claim QUEUED job from metadata
    ├─ For each table:
    │    ├─ planner: PK / Date / UUID chunks + AdaptiveChunkSizer
    │    ├─ queue.Enqueue (bbolt — skip if chunks already queued for resume)
    │    └─ per chunk:
    │         ├─ queue.ClaimChunk → extractor.RunWithOptions (go-mssqldb)
    │         ├─ MigrationColumnTransformPipeline (PII masking)
    │         ├─ loader.RunToTargetTable[Upsert] (pgx binary COPY)
    │         ├─ queue.UpdateStatus → LOADED; SetCheckpoint
    │         └─ sizer.NextSize(observed_ms) or RampDownHard on quarantine
    │
    └─ UPDATE migration_jobs status + totals; append job logs

GET /api/v1/migrations/{id}/progress  ← Python reads metadata written by Go
```

### Phased target DDL lifecycle

Bulk data migration deliberately splits **load-time DDL** from **post-load DDL** so COPY/INSERT stays fast and identity values from the source can be inserted explicitly.

| Phase | When | What is created on PostgreSQL | Module |
|---|---|---|---|
| **Minimal load schema** | Before Go COPY | Columns (plain types), **primary key only** — no identity, defaults, secondary indexes, FKs, checks, triggers | `target_table_provisioner.py` (`MIGRATION_LOAD_DDL_POLICY = minimal_load`) |
| **Bulk data load** | Go worker | Rows copied with explicit source values (including identity column values) | `engine-go/internal/loader` |
| **Row validation** | After COMPLETED | L1 row-count parity (source vs target) | `go_migration_job_watcher.py` |
| **Post-migration finalize** | After validation pass (auto or manual) | Identity + sequence sync, secondary indexes, FKs, checks, defaults | `post_migration_finalizer.py` |

**SQL Server → PostgreSQL identity mapping (finalize step only):**

| SQL Server | PostgreSQL (after load) |
|---|---|
| `INT IDENTITY(1,1)` | `integer GENERATED BY DEFAULT AS IDENTITY` + `setval(pg_get_serial_sequence(…), GREATEST(MAX(col), seed))` |
| `BIGINT IDENTITY(seed, increment)` | `bigint GENERATED BY DEFAULT AS IDENTITY (INCREMENT BY n …)` + `setval` |

`GENERATED BY DEFAULT` (not `ALWAYS`) preserves SQL Server semantics: auto-fill when omitted, allow explicit inserts for admin/data-fix paths.

**Index policy:** non-clustered secondary indexes from `sys.indexes` are **not** created during provisioning. At finalize, they are emitted via `PostMigrationDdlGenerator.generate_secondary_index()` (reuses `DdlGenerator.generate_index_ddl_from_discovery`). Unsupported types (columnstore, spatial, XML) are inventoried with `unsupported_reason` and skipped. Optional `CREATE INDEX CONCURRENTLY` via `create_indexes_concurrently` job flag.

**Constraint policy:** FK and CHECK constraints use PostgreSQL `NOT VALID` → `VALIDATE CONSTRAINT` so validation runs after bulk load without blocking inserts during migration.

### Post-migration finalize

#### Domain layer (`domains/migration/`)

| Module | Responsibility |
|---|---|
| `deferred_schema_catalog.py` | `DeferredSchemaCatalogBuilder` queries `sys.identity_columns`, `sys.indexes`, `sys.foreign_keys`, `sys.check_constraints`, `sys.default_constraints`, `sys.triggers`; produces `DeferredTableSchema` dataclass serialized to `plan_config.deferred_schema` |
| `post_migration_ddl_generator.py` | Emits finalize DDL: identity alter + setval, indexes, FK/CHECK NOT VALID pairs, column defaults (e.g. `getdate()` → `CURRENT_TIMESTAMP`) |
| `post_migration_finalize_models.py` | `PostMigrationFinalizeOptions`, `PostMigrationFinalizeState`, per-object status enums (`pending` / `applied` / `failed` / `unsupported` / `skipped`) |

#### Application layer (`application/go_engine_migration/`)

| Module | Responsibility |
|---|---|
| `target_table_provisioner.py` | `build_create_table_ddl()` — minimal load schema only |
| `post_migration_finalizer.py` | `PostMigrationFinalizer.finalize_table()`, `finalize_migration_job()`, `get_finalize_status()` |
| `go_migration_job_dispatcher.py` | Captures deferred catalog at dispatch; stores in `migration_table_plans.plan_config` |
| `go_migration_job_watcher.py` | Runs finalize after successful L1 validation when `finalize_after=true` |

#### API

| Method | Path | Role |
|---|---|---|
| `GET` | `/api/v1/migrations/{job_id}/post-migration` | Inventory + applied status per table/object |
| `POST` | `/api/v1/migrations/{job_id}/post-migration/finalize` | Operator-triggered finalize with option overrides |

`POST /api/v1/migrations` accepts finalize flags: `finalize_after`, `finalize_identities`, `finalize_indexes`, `finalize_foreign_keys`, `finalize_check_constraints`, `finalize_defaults`, `finalize_triggers`, `create_indexes_concurrently`.

#### UI

- **Job detail** (`/migrations/{jobId}`) — link to post-migration finalize
- **Finalize dashboard** (`/migrations/{jobId}/post-migration`) — per-table deferred inventory, per-object status, option checkboxes, **Run post-migration finalize** action

#### Triggers

Triggers are **discovered and displayed** in the finalize inventory but **not auto-applied by default** (`finalize_triggers=false`). T-SQL → PL/pgSQL trigger conversion remains in the transpilation pipeline; operators enable trigger finalize only after manual review.

**Local product install:** `deploy/install/sql-optima.sh` (pre-built images). **Local dev:** `python start.py --all` starts API + Go engine + UI. **Developer Docker:** `docker compose up` includes the `migration-engine` service (lab stack; Grafana uses host 3508).

---

## 11. Go Data Plane (`engine-go/`)

The `engine-go/` directory is a single Go module (`go 1.23`) containing the production data plane. **All packages compile and test with no live database required** (`go test ./...`); optional integration tests use `-tags integration`.

### Runtime wiring (`cmd/migration-engine/main.go`)

1. Load `config/default.toml` + `MIGRATION_*` env overrides
2. Open bbolt queue at `MIGRATION_QUEUE_PATH`
3. Connect metadata PostgreSQL (`MIGRATION_DATABASE_METADATA_URL`)
4. Initialise `AdaptiveChunkSizer` from `[chunks]` config
5. Start `MigrationEngineWorkerLoop` — poll/claim jobs, run `MigrationGoJobHandler`
6. Graceful shutdown on SIGINT/SIGTERM

`MigrationEngineRuntime` passes `{Queue, ChunkCfg, WorkerID, Sizer}` into table movers. Sequential and parallel strategies both claim chunks from bbolt; parallel workers use `ClaimChunk` with per-worker sizer clones.

### Package overview

```
migration-engine (binary: cmd/migration-engine)
  ├── internal/core         shared types + type_mapping
  │     ChunkPlan, ChunkStatus, JobStatus, Command, CellValue, EngineError
  │     type_mapping: SQL Server → LogicalType → PostgreSQL conversion matrix
  ├── internal/queue        → bbolt (embedded key-value store)
  │     ChunkQueue: Enqueue, ClaimChunk, ClaimNextPending, UpdateStatus,
  │                PeekNextPending, SetCheckpoint, SetCommand
  ├── internal/metadata     → pgx/v5 (PostgreSQL)
  │     MetadataClient: GetCommand, AckCommand, UpdateJobStatus, SyncChunkProgress
  │     CommandPoller: PollOnce (LISTEN/NOTIFY + 500 ms fallback)
  ├── internal/metrics      → OpenTelemetry 1.34
  │     EngineMetrics: rows_extracted/_loaded, chunk_duration, active_workers,
  │                    queue_depth, cdc_lag_ms
  ├── internal/planner      (pure, no I/O)
  │     AdaptiveChunkSizer, PrimaryKeyChunker, DateChunker
  ├── internal/extractor    → go-mssqldb
  │     QueryBuilder (injection-safe), ExtractionSchema, StreamChunk
  ├── internal/loader       → pgx/v5 CopyIn
  │     StatementBuilder, BinaryCopyEncoder, CopyIn
  ├── internal/cdc          (pure, no I/O)
  │     CdcOperation, Lsn, CdcEvent, BuildApplyStatement, CdcStateMachine
  └── internal/config       → viper
        Config: database, logging, engine tuning parameters
```

### Chunk planner

- **`AdaptiveChunkSizer`** — after each chunk, ramps the next size up (×1.5) if the observed duration was < 50 % of target, down (×0.7) if > 150 %, clamped to `[min, max]`. Converges chunk size on a target wall-clock duration.
- **`PrimaryKeyChunker`** — splits an integer PK range `[min, max]` into contiguous, non-overlapping, complete-coverage `[start, end]` ranges.
- **`DateChunker`** — same guarantees over a date span by N-day windows.

### Data path

```
SQL Server rows
   │  extractor.StreamChunk(): go-mssqldb streaming, one row at a time
   ▼  row_to_cells() — typed per ExtractionSchema LogicalType
[]CellValue
   │  loader.BinaryCopyEncoder.Encode()
   ▼
PostgreSQL binary COPY payload  (PGCOPY header · per-row framing · trailer)
   │  loader.CopyIn(): pgx/v5 CopyFrom
   ▼
COPY <table> FROM STDIN WITH (FORMAT binary)
```

**Type coverage** (byte-exact binary encoding, unit-tested):

| Group | Types | Notes |
|---|---|---|
| Numeric / bool | Bool, Int16, Int32, Int64, Float32, Float64 | big-endian |
| Text / binary | String, Bytes | UTF-8 / raw bytes |
| Temporal | Date, Timestamp, TimestampTz, Time | PostgreSQL 2000-epoch shift applied at encode time |
| Identity | UUID | 16 raw bytes |

### Injection safety

Both query builders quote identifiers with the dialect escape-doubling (`]]` for SQL Server, `""` for PostgreSQL) and pass all range/LSN values as bound parameters (`@P1`, `$1`) — never interpolated. Dedicated tests assert that a hostile identifier stays inside its quoted context.

### bbolt bucket layout

| Bucket | Key | Value | Purpose |
|---|---|---|---|
| `chunks` | `{job_id}/{chunk_id}` | JSON `ChunkPlan` | Authoritative chunk data |
| `status_idx` | `{job_id}/{STATUS}/{chunk_id}` | `""` | Secondary index for status queries |
| `commands` | `{job_id}` | JSON `Command` | Current pending command per job |
| `checkpoints` | `{job_id}/{schema.table}` | `{chunk_id}` | Last successfully loaded chunk |

All writes use bbolt transactions — a crash cannot leave a chunk in an inconsistent state.

---

## 12. Replication Architecture (CDC)

Replication follows **hexagonal architecture**: the API calls `ReplicationService` (application), which delegates runtime wiring to `ReplicationRuntimeManager` and persists state via `ReplicationStreamRepository`. Domain logic for schema drift and identifier validation lives in `domains/replication/`. Low-level capture/apply primitives remain in `apps/replicator/`.

### Layer map

| Layer | Key modules |
|---|---|
| API | `apps/api/routers/replication_router.py` |
| Application | `application/replication_service.py`, `application/replication_runtime.py` |
| Domain | `domains/replication/schema_drift_detector.py`, `validators.py`, `entities.py` |
| Infrastructure | `infrastructure/replication/message_bus.py`, `change_consumer.py`, `sqlserver_watermark_adapter.py` |
| Replicator library | `apps/replicator/capture/`, `apply/`, `orchestrator/state_machine.py` |
| Ports | `shared/contracts/replication_ports.py` |

### End-to-end pipeline (Python control plane)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Next.js /replication  →  /api/v1/replication/streams/*                │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────────┐
│  ReplicationService                                                      │
│    create → schema drift concerns → replication_streams (metadata DB)     │
│    start  → ReplicationRuntimeManager.start_stream()                    │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
        ┌───────────────────────┴───────────────────────┐
        │                                               │
┌───────▼────────┐                              ┌───────▼────────┐
│ CaptureAgent   │                              │ Target asyncpg │
│ SqlServer      │   InMemoryChangeBus          │ ChangeApplier  │
│ WatermarkAdapter│  (bounded queue)            │ + Dedup + CP   │
│ poll loops     │ ──LoopbackPublisher──►       │ UPSERT/DELETE  │
└────────────────┘                              └────────────────┘
        │ optional REPLICATION_RABBITMQ_URL
        └─► RabbitMqBridgeConsumer (aio-pika) ──► same handler

State machine (9 states):
IDLE → STARTING → SNAPSHOTTING → CDC_CATCHUP → CDC_STREAMING
                                               ↓
                                     PAUSED / STOPPING / FAILED / COMPLETED

Checkpointing:
  Per-table LSN/watermark bytes in target PostgreSQL._replication_checkpoint
  Stream-level last_checkpoint_lsn + events_* counters in replication_streams
```

### Security & resource constraints

- **Identifiers** — `validate_identifier()` before any dynamic schema/table/column name; watermark SQL uses bound parameters only (`SqlServerWatermarkAdapter`).
- **Apply path** — `ChangeApplier` never interpolates user data into SQL strings; uses `$1…$n` placeholders.
- **Memory** — `InMemoryChangeBus` defaults to 2000 events (`REPLICATION_QUEUE_SIZE`); `Deduplicator` LRU capped (`max_size`); no `flushdb()` on Redis (scoped `dedup:*` keys only).
- **Secrets** — connection passwords resolved via `SecretsManager` / vault ref; never logged.

### Schema drift detection

At stream **create**, `detect_schema_drift()` compares source vs target column sets and primary keys:

| Level | Example |
|---|---|
| `blocker` | Target table missing — migration required first |
| `warning` | Source column absent on target; PK mismatch |
| `info` | Extra column on target only |

Streams with blockers cannot be **started** until the target schema is provisioned.

### Go CDC package (`internal/cdc`) — future data-plane path

The `cdc` package implements all CDC logic. The live `go-mssqldb` read and `pgx/v5` apply I/O reuses the extractor and loader packages:

```
SQL Server CDC tables (cdc.{capture}_CT)
  └── cdc.BuildCaptureReadQuery()
        SELECT __$start_lsn, __$seqval, __$operation … WHERE __$start_lsn > @P1
        ORDER BY __$start_lsn, __$seqval        (parameterised on the checkpoint LSN)
  └── cdc.CdcOperation.FromCode()   1=DELETE 2=INSERT 3=UPDATE-before 4=UPDATE-after
  └── cdc.OrderForApply()           sort by (commit_lsn, seq_val)
  └── cdc.BuildApplyStatement()
        DELETE       → DELETE FROM t WHERE pk = $1 …
        INSERT/U-aft → INSERT … VALUES ($1…) ON CONFLICT (pk) DO UPDATE/NOTHING
        UPDATE-before→ skipped (informational)
  └── cdc.Lsn                       10-byte big-endian, total ordering, hex round-trip
  └── cdc.CdcStateMachine            guards the 9-state lifecycle transitions
        checkpoint LSN → replication_streams.last_checkpoint_lsn in metadata DB
```

The 9-state machine (`IDLE → STARTING → SNAPSHOTTING → CDC_CATCHUP →
CDC_STREAMING → PAUSED/STOPPING/FAILED/COMPLETED`) rejects illegal transitions
(e.g. it cannot skip the snapshot).

---

## 13. Layer Dependencies

```
┌────────────────────────────────────────────────────────────────┐
│  API layer (apps/api/routers/)                                  │
│  Depends on: Application services only                        │
└────────────────────────┬───────────────────────────────────────┘
                         │
┌────────────────────────▼───────────────────────────────────────┐
│  Application services (application/)                            │
│  Depends on: Domain logic + Repositories (via ports)           │
└──────────────┬─────────────────────────────┬───────────────────┘
               │                             │
┌──────────────▼─────────┐   ┌───────────────▼──────────────────┐
│  Domain layer (domains/)│   │  Infrastructure layer            │
│  Pure Python, no I/O   │   │  (infrastructure/metadata_db/,   │
│  Depends on:           │   │   sqlserver/, postgres/)         │
│  shared kernel only    │   │  Depends on: Domain + shared     │
└──────────────┬──────────┘   └──────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────────┐
│  Shared kernel (shared/)                                         │
│  Depends on: nothing external                                   │
│  database_object.py, ddl_identifier.py,                        │
│  secrets_manager.py, structured_logging.py                     │
└─────────────────────────────────────────────────────────────────┘
```

**Key rule:** Arrows point inward. The domain layer never imports from infrastructure or API. Repositories are accessed via port interfaces defined in `shared/contracts/`.

**Replication example:** `replication_router` → `replication_service` → `domains/replication` (drift/validators) + `ReplicationStreamRepository` + `ReplicationRuntimeManager` → `apps/replicator` capture/apply adapters. The replicator library does not import FastAPI or SQLAlchemy models directly.

---

## 14. Key Design Decisions

| Decision | Choice | Why |
|---|---|---|
| **No regex SQL transformation** | All transformations via AST (SQLGlot) | Regex on SQL produces incorrect results for edge cases; AST is the only safe approach |
| **DDL identifier quoting** | `quote_pg_ident()` escapes inner `"` by doubling | Old `f'"{name}"'` didn't escape embedded quotes — malformed SQL for names with `"`. Doubling per SQL-92 §5.2 is the correct escape |
| **API versioning** | All routes under `/api/v1`; 308 redirects for flat paths | Allows future `/api/v2` without breaking existing clients; 308 keeps the deprecation window explicit |
| **Metadata store** | PostgreSQL (SQLite for dev) via SQLAlchemy | Shared between Python and Go; supports concurrent readers; Alembic for schema evolution |
| **Password encryption** | Fernet + random PBKDF2 salt + versioned format `v2:key_id:…` | Random salt prevents rainbow table attacks; `key_id` enables key rotation without brute-forcing which key encrypted each value |
| **Secrets rotation** | `rotate(ciphertexts, new_key)` re-encrypts batch; output always v2 | Stateless — caller commits the batch transactionally; doesn't mutate the SecretsManager instance |
| **Auth token storage** | sha256(refresh_token) in DB | Never stores raw tokens; breach of session table doesn't yield usable tokens |
| **Go for data plane** | `go-mssqldb` (SQL Server) + `pgx/v5` (PostgreSQL) | `pyodbc` is synchronous and blocks the event loop; Python cannot achieve the throughput target. Go was chosen over Rust to eliminate the ~9 GB RocksDB + Arrow build artefacts and C++ toolchain dependency |
| **bbolt for queue** | Embedded, no external service | RabbitMQ/Kafka add operational complexity; bbolt is crash-safe with zero extra services and no C++ build dependency |
| **PostgreSQL epoch shift in loader** | `BinaryCopyEncoder` shifts Unix-epoch temporals to the PostgreSQL 2000 epoch | PostgreSQL binary `date`/`timestamp` use a 2000-01-01 epoch. Doing the shift once at encode time keeps the extractor producing standard values |
| **SQLite default** | `sqlite+aiosqlite:///migration_platform.db` | Zero-config for development; switch to PostgreSQL in prod by changing one env var |
| **`jti` claim in JWTs** | UUID per token | Prevents identical tokens generated in the same second; enables future revocation |
| **Timing-safe auth** | Always run bcrypt for missing users | Prevents user-existence oracle attacks via response time differences |
| **pyodbc in thread pool** | `asyncio.get_running_loop().run_in_executor()` | pyodbc has no async driver; `get_running_loop()` (not deprecated `get_event_loop()`) prevents event-loop blocking |
| **Startup readiness check** | Hard fail on DB unreachable, soft warn on ODBC absent | DB unreachable means no state can be persisted — the API cannot function. Missing ODBC only affects SQL Server sources; REST API, UI, and PostgreSQL-only operations still work |
| **Chunk boundary semantics** | Half-open `[start, end)` in planner + extract query | Prevents silent row skips when chunk end was treated as inclusive |
| **Product editions** | `MIGRATION_EDITION` + HMAC `MIGRATION_LICENSE_KEY` | Gates features per SKU (assess/migrate/replicate/enterprise); blocks DEV-LOCAL in production |
| **Pre-migration snapshot** | `SnapshotGate` + `require_target_snapshot` on API | Ensures target pg_dump exists before destructive bulk load; dev override via env |
| **Phased target DDL** | Minimal load schema + post-migration finalize | Identity, secondary indexes, FKs, and checks deferred until after bulk COPY so inserts stay fast and source identity values load explicitly; `GENERATED BY DEFAULT AS IDENTITY` + `setval` applied only after validation |
| **PII masking** | Column transforms in Go dispatch JSON | Compliance — mask at extract/transform before load; auto-discovery via `pii_classifier` |
| **Observability** | `/metrics` Prometheus text + `GET /admin/slos` | Operators scrape counters; SLO doc lives in code + OPERATIONS.md |
| **Cutover rollback window** | `cutover_checkpoints.committed=false` for 24 h | Operators can rollback to pre-cutover state before commit closes the window |

---

## 15. Status Summary

| Area | Status |
|---|---|
| Security (JWT, RBAC, bcrypt, CORS, SQL injection, metadata security audit) | ✅ Done |
| Metadata DB (PostgreSQL/SQLite, Alembic, repositories incl. cutover/programs/audit) | ✅ Done |
| Auth (DB users, refresh tokens, role guards, JWT dual-secret rotation) | ✅ Done |
| API decomposition (15+ routers: replication, programs, workflows, alerts, admin SLOs/usage) | ✅ Done |
| Assessment engine (SAFE/WARNING/BLOCKER, complexity scores, executive ROI report) | ✅ Done |
| T-SQL → PL/pgSQL transpiler (40+ constructs, parse unblockers, pgparse repair loop) | ✅ Done |
| Hardening (rate limiting, Docker healthchecks, startup checks, DDL quoting, secrets rotation, chunk boundary fix) | ✅ Done |
| Go data plane: planner, extractor, loader, queue, worker loop, dispatch parity | ✅ Done |
| Go orchestration: bbolt queue + adaptive sizer wired through table movers | ✅ Done |
| Python control plane: dispatch, commands, watcher, snapshot gate, PII masking, **post-migration finalize** | ✅ Done |
| L1–L4 validation (row count, aggregates, chunk hash, sampling, row-sample compare, equivalence harnesses) | ✅ Done |
| Schema comparison (comparison tree, significant diffs, dual-pane UI) | ✅ Done |
| Post-migration finalize (deferred schema catalog, identity/index/FK/check/default apply, UI dashboard) | ✅ Done |
| Migration wizard auto-assessment + per-table concerns | ✅ Done |
| Replication control plane (API, service, runtime, UI, CDC preflight, schema drift) | ✅ Done |
| Cutover workflow (checkpoints, rollback, connection-switch manifest, write-freeze) | ✅ Done |
| Migration programs / waves API with sign-off | ✅ Done |
| Project / JWT scoping (`shared/tenancy/project_scope.py`, Alembic 006) | ✅ Done — admins unscoped; legacy rows without `project_id` remain visible |
| Licensing & editions (HMAC keys, feature gates, Helm chart, usage metering) | 🟡 Partial — signed images + license server pending |
| Observability (`/metrics`, SLO API, alert webhooks) | ✅ Done |
| Next.js UI (full dashboard; Playwright smoke + core-flow + jest-axe a11y + Lighthouse CI; Programs Gantt) | ✅ Done — Lighthouse CI on `/login`; Programs wave Gantt at `/programs` |
| SQL Server native CDC provider wired to CaptureAgent (`SqlServerCdcProvider`) | ✅ Done — ABC + checkpoint resume + snapshot FSM |
| CDC live I/O in Go data plane (`go-mssqldb` read + `pgx/v5` apply around `cdc` package) | ✅ Done — `internal/cdc/io` CaptureReader/ApplyWriter + env worker |
| Grafana dashboards + OTLP provider init in the Go binary | ✅ Done — OTLP gRPC `:4317`, metrics wired to workers, Migration Engine dashboard |
| Expanded live integration tests (full docker-compose stack; golden e2e in weekly CI) | 🟡 Partial — API discover→migrate→validate + Playwright core flows; live dual-DB optional |
| Privilege hard-fail on elevated DB principals (§12.6) | ✅ Done — BLOCKER + `assert_least_privilege` gate (`MIGRATION_ALLOW_ELEVATED_PRIVILEGES` override) |
| JWT RS256 dual-mode (§12.5) | ✅ Done — optional `MIGRATION_JWT_PRIVATE_KEY` / `PUBLIC_KEY`; HS256 default + legacy accept |
| Platform error UI (§13.11) | ✅ Done — `PlatformError` + `ApiError.payload` + ErrorBoundary |
| Chaos / resumability + idempotent double-run tests (§11.3–11.4) | ✅ Done — mid-failure resume + ChunkedMigration double-run |

---

## Related documentation

| Document | Purpose |
|---|---|
| [README.md](README.md) | Docker install + developer quickstart |
| [deploy/install/INSTALL.md](deploy/install/INSTALL.md) | Website / Docker-only customer install |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development setup and pull request guidelines |
| [SECURITY.md](SECURITY.md) | Vulnerability reporting + pointer to production hardening |
| [OPERATIONS.md](OPERATIONS.md) | Runbooks, SLOs, cutover, programs |
| [PACKAGING.md](PACKAGING.md) | Editions, licensing, Docker install, Helm, metering |
| [RELEASE.md](RELEASE.md) | Version history and upgrade notes |
| [CLAUDE.md](CLAUDE.md) | Agent/contributor quick reference (local; may be gitignored) |
| `docs/SECURITY.md` | Extra production-hardening notes (local `docs/` tree; gitignored) |
