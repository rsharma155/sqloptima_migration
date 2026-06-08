# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""MigrationService — orchestrates migration lifecycle (Go engine control plane).

In-process job/task state lives in a dedicated :class:`JobRegistry` (the hot-path
cache); the metadata DB is the durable store. Data movement runs in the Go
``migration-engine`` worker; Python dispatches jobs and watches completion.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from application.audit_service import AuditService
from application.notification_service import create_notification_service
from infrastructure.metadata_db.models import MigrationJobRecord, MigrationTablePlanRecord
from infrastructure.metadata_db.session import AsyncSessionFactory
from shared.logging.structured_logging import get_logger
from shared.security.audit_log import AuditAction

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# In-process state (populated at startup, kept in sync with the DB)
# ---------------------------------------------------------------------------

from application.job_registry import JobRegistry  # noqa: E402 — after logger setup
from domains.migration.migration_engine import (  # noqa: E402 — after logger setup
    MigrationJob,
    MigrationStatus,
    MigrationStrategy,
    TableMigrationPlan,
)

_TERMINAL_STATUSES = frozenset({
    MigrationStatus.COMPLETED,
    MigrationStatus.PARTIAL,
    MigrationStatus.FAILED,
    MigrationStatus.STOPPED,
})
_TERMINAL_DB_STATUSES = frozenset({"completed", "partial", "failed", "stopped"})
_COMPLETED_TABLE_STATUSES = frozenset({"completed", "done"})
_FINISHED_TABLE_STATUSES = frozenset({"completed", "done", "failed", "skipped"})

_registry = JobRegistry()

# Debouncing for DB writes during active migration (avoid hammering the DB on
# every row-progress callback).
_jobs_last_save: float = 0.0
_JOBS_SAVE_INTERVAL: float = 2.0
_jobs_dirty: bool = False

# ---------------------------------------------------------------------------
# DB persistence helpers
# ---------------------------------------------------------------------------

from sqlalchemy import delete as _sa_delete, select as _sa_select  # noqa: E402
from sqlalchemy.orm import selectinload as _selectinload  # noqa: E402


async def _append_job_log_durable(
    job_id: UUID | str,
    message: str,
    *,
    level: str = "info",
) -> None:
    """Persist a log line to migration_job_logs (no in-memory accumulation)."""
    from application.go_engine_migration.durable_migration_job_log_writer import (
        DurableMigrationJobLogWriter,
    )

    await DurableMigrationJobLogWriter().append(str(job_id), message, level=level)


async def _persist_job_status(
    job_id: UUID,
    status: MigrationStatus,
    *,
    error: str | None = None,
    set_completed_at: bool = False,
) -> None:
    """Write job status to migration_jobs immediately (durable control-plane state)."""
    async with AsyncSessionFactory() as session:
        record = await session.get(MigrationJobRecord, str(job_id))
        if record is None:
            return
        record.status = _status_str(status)
        record.updated_at = datetime.now(UTC)
        if error is not None:
            record.error = error
        if set_completed_at:
            record.completed_at = datetime.now(UTC)
        await session.commit()


async def _record_migration_audit(
    action: AuditAction,
    job_id: str,
    details: dict[str, Any] | None = None,
    *,
    project_id: str | None = None,
    success: bool = True,
    error_message: str | None = None,
) -> None:
    try:
        async with AsyncSessionFactory() as session:
            await AuditService(session).record(
                action,
                actor="system",
                resource=f"migration/{job_id}",
                details=details,
                project_id=project_id,
                success=success,
                error_message=error_message,
            )
    except Exception as exc:
        logger.warning("audit_record_failed", action=action.value, error=str(exc))


def _status_str(status: MigrationStatus | str) -> str:
    if hasattr(status, "value"):
        return str(status.value).lower()
    return str(status).lower()


def _go_job_data_complete(record: MigrationJobRecord) -> bool:
    """True when all table plans finished but job-level status may still be stale."""
    if not record.table_plans:
        return False
    table_statuses = [(p.status or "").lower() for p in record.table_plans]
    if not table_statuses or not all(s in _FINISHED_TABLE_STATUSES for s in table_statuses):
        return False
    total = int(record.tables_total or len(record.table_plans))
    return total > 0 and len(table_statuses) >= total


async def _reconcile_go_job_completion(session: Any, record: MigrationJobRecord) -> bool:
    """Promote stuck running/queued Go jobs to completed when data plane finished."""
    if getattr(record, "executor", "go") != "go":
        return False
    db_status = (record.status or "").lower()
    if db_status in _TERMINAL_DB_STATUSES:
        return False
    if not _go_job_data_complete(record):
        return False
    table_statuses = [(p.status or "").lower() for p in record.table_plans]
    if any(s == "failed" for s in table_statuses):
        if any(s in _COMPLETED_TABLE_STATUSES for s in table_statuses):
            record.status = MigrationStatus.PARTIAL.value
        else:
            record.status = MigrationStatus.FAILED.value
    else:
        record.status = MigrationStatus.COMPLETED.value
    record.completed_at = record.completed_at or datetime.now(UTC)
    record.updated_at = datetime.now(UTC)
    await session.commit()
    logger.info(
        "go_job_status_reconciled",
        job_id=record.migration_job_id,
        previous_status=db_status,
    )
    return True


def _derive_job_status(
    job: MigrationJob,
    record: MigrationJobRecord | None = None,
) -> MigrationStatus:
    """Prefer durable DB / per-table state over stale in-memory job status."""
    if record and record.status:
        try:
            db_status = MigrationStatus(record.status.lower())
            if db_status in _TERMINAL_STATUSES:
                return db_status
            # Go worker writes running/paused to metadata; in-memory cache may still say queued.
            if db_status in (MigrationStatus.RUNNING, MigrationStatus.PAUSED, MigrationStatus.QUEUED):
                if _go_job_data_complete(record):
                    return MigrationStatus.COMPLETED
                return db_status
        except ValueError:
            pass

    # Honor terminal status already merged onto the in-memory job (e.g. FAILED from DB).
    if job.status in _TERMINAL_STATUSES:
        return job.status

    if not job.tables:
        return job.status

    table_statuses = [(t.status or "").lower() for t in job.tables]
    failed_count = sum(1 for s in table_statuses if s == "failed")
    completed_count = sum(1 for s in table_statuses if s in _COMPLETED_TABLE_STATUSES)
    pending = any(
        s in ("migrating", "running", "in_progress", "pending", "queued", "")
        for s in table_statuses
    )
    if not pending and failed_count > 0:
        if completed_count > 0:
            return MigrationStatus.PARTIAL
        return MigrationStatus.FAILED
    if table_statuses and all(s in _COMPLETED_TABLE_STATUSES for s in table_statuses):
        return MigrationStatus.COMPLETED
    if any(s in ("migrating", "running", "in_progress") for s in table_statuses):
        return MigrationStatus.RUNNING

    if record and record.status:
        try:
            return MigrationStatus(record.status.lower())
        except ValueError:
            pass

    return job.status


def _merge_record_into_job(job: MigrationJob, record: MigrationJobRecord) -> None:
    job.status = _derive_job_status(job, record)
    job.error_message = getattr(record, "error", None)
    job.executor = getattr(record, "executor", job.executor)
    job.updated_at = getattr(record, "updated_at", job.updated_at) or job.updated_at
    job.started_at = getattr(record, "started_at", None)
    job.completed_at = getattr(record, "completed_at", None)
    job._record_rows_migrated = int(record.rows_migrated or 0)  # type: ignore[attr-defined]
    job._record_rows_total = int(record.rows_total or 0)  # type: ignore[attr-defined]
    cfg = getattr(record, "config", None) or {}
    if cfg.get("procedural_migration"):
        job.procedural_migration = cfg["procedural_migration"]
    if cfg.get("finalize_options"):
        job.finalize_options = cfg["finalize_options"]

    plans_by_name = {t.table_name: t for t in record.table_plans}
    for plan in job.tables:
        persisted = plans_by_name.get(plan.table_name)
        if persisted is None:
            continue
        plan.status = persisted.status
        plan.rows_migrated = persisted.rows_migrated or 0
        if persisted.row_count_estimate:
            plan.row_count_estimate = persisted.row_count_estimate
        elif plan.rows_migrated and (plan.status or "").lower() in _COMPLETED_TABLE_STATUSES:
            plan.row_count_estimate = plan.rows_migrated


def _table_progress_percentage(plan: TableMigrationPlan) -> float:
    rows = plan.rows_migrated or 0
    estimate = plan.row_count_estimate or 0
    if estimate > 0:
        return min(100.0, rows / estimate * 100.0)
    status = (plan.status or "").lower()
    if status in _COMPLETED_TABLE_STATUSES:
        return 100.0 if rows > 0 else 0.0
    return 0.0


async def save_jobs_async(*, force: bool = False) -> None:
    """Upsert all in-memory jobs to the metadata DB (debounced to 2 s unless *force*)."""
    global _jobs_last_save, _jobs_dirty
    now = datetime.now(UTC).timestamp()
    if not force and now - _jobs_last_save < _JOBS_SAVE_INTERVAL:
        _jobs_dirty = True
        return
    _jobs_dirty = False
    _jobs_last_save = now
    try:
        # Iterate a lock-protected snapshot so a concurrent start/stop mutating
        # the registry cannot raise "dict changed size during iteration".
        jobs_snapshot = await _registry.snapshot()
        async with AsyncSessionFactory() as session:
            for jid, job in jobs_snapshot:
                executor = getattr(job, "executor", "go")
                status_value = _status_str(job.status)
                existing = await session.get(MigrationJobRecord, str(jid))

                # Go worker owns status, row counters, and table plans after dispatch.
                # Never write status from the in-memory cache — it races with the worker
                # and can clobber a freshly written "completed" back to "running".
                if executor == "go" and existing is not None:
                    existing.source_project_connection_id = str(job.source_connection_id)
                    existing.target_project_connection_id = str(job.target_connection_id)
                    if getattr(job, "error_message", None) is not None:
                        existing.error = job.error_message
                    if getattr(job, "project_id", None):
                        existing.project_id = job.project_id
                    merged_config = dict(existing.config or {})
                    if getattr(job, "dispatch_config", None):
                        merged_config.update(job.dispatch_config)
                    if getattr(job, "finalize_options", None):
                        merged_config["finalize_options"] = job.finalize_options
                    if getattr(job, "procedural_migration", None):
                        merged_config["procedural_migration"] = job.procedural_migration
                    if merged_config:
                        existing.config = merged_config
                    existing.updated_at = (
                        job.updated_at if hasattr(job, "updated_at") else datetime.now(UTC)
                    )
                    continue

                job_config: dict[str, Any] = {}
                if getattr(job, "dispatch_config", None):
                    job_config.update(job.dispatch_config)
                if getattr(job, "finalize_options", None):
                    job_config["finalize_options"] = job.finalize_options
                if getattr(job, "procedural_migration", None):
                    job_config["procedural_migration"] = job.procedural_migration

                job_rec = MigrationJobRecord(
                    migration_job_id=str(jid),
                    source_project_connection_id=str(job.source_connection_id),
                    target_project_connection_id=str(job.target_connection_id),
                    status=status_value,
                    error=getattr(job, "error_message", None),
                    project_id=getattr(job, "project_id", None),
                    config=job_config or None,
                    executor=executor,
                    created_at=job.created_at if hasattr(job, "created_at") else datetime.now(UTC),
                    updated_at=job.updated_at if hasattr(job, "updated_at") else datetime.now(UTC),
                )
                await session.merge(job_rec)
                await session.execute(
                    _sa_delete(MigrationTablePlanRecord).where(
                        MigrationTablePlanRecord.migration_job_id == str(jid)
                    )
                )
                for t in getattr(job, "tables", []):
                    session.add(MigrationTablePlanRecord(
                        migration_job_id=str(jid),
                        table_name=t.table_name,
                        schema_name=t.schema_name,
                        target_schema=getattr(t, "target_schema", "public"),
                        strategy=t.strategy.value if hasattr(t.strategy, "value") else str(t.strategy),
                        chunk_size=getattr(t, "chunk_size", 10000),
                        parallel_workers=getattr(t, "parallel_workers", 4),
                        status=getattr(t, "status", "pending"),
                        rows_migrated=getattr(t, "rows_migrated", 0),
                        row_count_estimate=getattr(t, "row_count_estimate", 0),
                        columns=getattr(t, "columns", None),
                        plan_config={
                            "column_transforms": getattr(t, "column_transforms", None),
                            "column_sensitivity": getattr(t, "column_sensitivity", None),
                            "column_types": getattr(t, "column_types", None),
                        },
                    ))
            await session.commit()
    except Exception as exc:
        logger.error("Failed to save jobs to metadata DB", error=str(exc))


async def load_jobs() -> None:
    """Load all persisted jobs from DB into the in-memory cache at startup."""
    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                _sa_select(MigrationJobRecord).options(
                    _selectinload(MigrationJobRecord.table_plans)
                )
            )
            records = list(result.scalars().all())
        for record in records:
            try:
                # Any job that was RUNNING when the server last stopped has no
                # active asyncio task now — mark it FAILED so it doesn't show
                # as perpetually running in the UI.
                persisted_status = MigrationStatus(record.status) if record.status else MigrationStatus.PENDING
                if persisted_status == MigrationStatus.RUNNING:
                    executor = getattr(record, "executor", "python")
                    if executor != "go":
                        persisted_status = MigrationStatus.FAILED
                        record.status = persisted_status.value

                job = MigrationJob(
                    job_id=UUID(record.migration_job_id),
                    source_connection_id=UUID(record.source_project_connection_id) if record.source_project_connection_id else UUID(int=0),
                    target_connection_id=UUID(record.target_project_connection_id) if record.target_project_connection_id else UUID(int=0),
                    project_id=getattr(record, "project_id", None),
                    status=persisted_status,
                    tables=[
                        TableMigrationPlan(
                            table_name=t.table_name,
                            schema_name=t.schema_name,
                            target_schema=getattr(t, "target_schema", "public"),
                            columns=t.columns if getattr(t, "columns", None) else ["*"],
                            row_count_estimate=t.row_count_estimate,
                            strategy=MigrationStrategy(t.strategy),
                            chunk_size=t.chunk_size,
                            parallel_workers=t.parallel_workers,
                            status=t.status,
                            rows_migrated=t.rows_migrated,
                        )
                        for t in record.table_plans
                    ],
                    error_message=getattr(record, "error", None),
                )
                job.executor = getattr(record, "executor", "go")
                job.dispatch_config = getattr(record, "config", None)
                cfg = getattr(record, "config", None) or {}
                if cfg.get("procedural_migration"):
                    job.procedural_migration = cfg["procedural_migration"]
                if cfg.get("finalize_options"):
                    job.finalize_options = cfg["finalize_options"]
                _registry.put(job)
            except Exception as exc:
                logger.warning("Skipping corrupt job record", job_id=record.migration_job_id, error=str(exc))
        logger.info("Jobs loaded from metadata DB", count=_registry.count())
        # Flush any status corrections (RUNNING → FAILED) back to DB.
        await save_jobs_async()
    except Exception as exc:
        logger.warning("Failed to load jobs, starting empty", error=str(exc))
        _registry.clear()


# ---------------------------------------------------------------------------
# Connector factory (needs SecretsManager for password decryption)
# ---------------------------------------------------------------------------

def _decrypt_password(entry: dict) -> str:
    from apps.api.dependencies import get_secrets
    pw = entry.get("password", "")
    secrets = get_secrets()
    if secrets and pw and ":" in pw:
        try:
            return secrets.decrypt(pw)
        except Exception:
            logger.warning("Failed to decrypt password, returning as-is")
    return pw


async def make_connector(entry: dict) -> tuple[Any, Any]:
    """Build a connector + config from a connection cache entry dict."""
    password = _decrypt_password(entry)
    if entry["type"] == "source":
        from infrastructure.sqlserver.sqlserver_connector import (
            SqlServerConnector,
            sqlserver_config_from_entry,
        )
        config = sqlserver_config_from_entry(entry, password=password)
        return SqlServerConnector(config), config
    else:
        from infrastructure.postgres.postgres_connector import (
            PostgresConnector,
            postgres_config_from_entry,
        )
        config = postgres_config_from_entry(entry, password=password)
        return PostgresConnector(config), config


# ---------------------------------------------------------------------------
# Public API for routers
# ---------------------------------------------------------------------------

def get_job(job_id: UUID) -> MigrationJob | None:
    return _registry.get(job_id)


async def refresh_job_from_metadata(job_id: UUID) -> MigrationJob | None:
    """Merge durable metadata DB state into the in-memory job (Go executor jobs)."""
    job = _registry.get(job_id)
    if job is None:
        return None

    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                _sa_select(MigrationJobRecord)
                .where(MigrationJobRecord.migration_job_id == str(job_id))
                .options(_selectinload(MigrationJobRecord.table_plans))
            )
            record = result.scalar_one_or_none()
            if record is None:
                return job
            await _reconcile_go_job_completion(session, record)
    except Exception as exc:
        logger.warning("Failed to refresh job from metadata", job_id=str(job_id), error=str(exc))
        return job

    async with _registry.lock:
        _merge_record_into_job(job, record)

    return job


async def refresh_all_jobs_from_metadata() -> None:
    """Bulk-merge metadata DB state into all in-memory jobs (for list endpoints)."""
    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                _sa_select(MigrationJobRecord).options(
                    _selectinload(MigrationJobRecord.table_plans)
                )
            )
            records = {r.migration_job_id: r for r in result.scalars().all()}
    except Exception as exc:
        logger.warning("Failed to bulk refresh jobs from metadata", error=str(exc))
        return

    async with _registry.lock:
        for jid, job in _registry.all_items():
            record = records.get(str(jid))
            if record is not None:
                _merge_record_into_job(job, record)


def build_progress_snapshot(job: MigrationJob) -> dict[str, Any]:
    """Build API progress payload from refreshed table plans (Go engine metadata)."""
    tables_progress: dict[str, dict[str, Any]] = {}
    total_rows_migrated = 0
    total_rows_estimate = 0

    for plan in job.tables:
        rows = plan.rows_migrated or 0
        estimate = plan.row_count_estimate or 0
        if estimate == 0 and rows > 0 and (plan.status or "").lower() in _COMPLETED_TABLE_STATUSES:
            estimate = rows
        pct = _table_progress_percentage(plan)
        tables_progress[plan.table_name] = {
            "table_name": plan.table_name,
            "schema_name": plan.schema_name,
            "total_rows_estimate": estimate,
            "row_count": estimate,
            "rows_migrated": rows,
            "percentage": round(pct, 1),
            "current_chunk": 0,
            "total_chunks": 0,
            "status": plan.status,
            "throughput_rows_per_sec": 0.0,
            "elapsed_seconds": 0.0,
            "estimated_remaining_seconds": 0.0,
        }
        total_rows_migrated += rows
        total_rows_estimate += estimate

    record_rows_migrated = int(getattr(job, "_record_rows_migrated", 0) or 0)
    record_rows_total = int(getattr(job, "_record_rows_total", 0) or 0)
    if record_rows_migrated > total_rows_migrated:
        total_rows_migrated = record_rows_migrated
    if record_rows_total > total_rows_estimate:
        total_rows_estimate = record_rows_total

    effective_status = _derive_job_status(job)
    if total_rows_estimate > 0:
        overall_pct = min(100.0, total_rows_migrated / total_rows_estimate * 100.0)
    elif effective_status == MigrationStatus.COMPLETED and total_rows_migrated > 0:
        overall_pct = 100.0
        total_rows_estimate = total_rows_migrated
    elif job.tables and all(
        (t.status or "").lower() in _COMPLETED_TABLE_STATUSES for t in job.tables
    ):
        overall_pct = 100.0
        if total_rows_migrated > 0:
            total_rows_estimate = total_rows_migrated
    else:
        overall_pct = 0.0

    started = getattr(job, "started_at", None) or job.created_at
    now = datetime.now(UTC)
    completed = getattr(job, "completed_at", None)
    is_terminal = effective_status in _TERMINAL_STATUSES
    end = completed if completed else (now if not is_terminal else now)
    elapsed = max((end - started).total_seconds(), 0.0) if started else 0.0
    throughput = (
        total_rows_migrated / elapsed
        if elapsed > 0 and total_rows_migrated > 0 and not is_terminal
        else (
            total_rows_migrated / elapsed
            if elapsed > 0 and total_rows_migrated > 0 and is_terminal
            else 0.0
        )
    )
    remaining_rows = max(total_rows_estimate - total_rows_migrated, 0)
    eta = (
        0.0
        if is_terminal
        else (remaining_rows / throughput if throughput > 0 else 0.0)
    )

    if elapsed > 0:
        for entry in tables_progress.values():
            entry["elapsed_seconds"] = elapsed
            if throughput > 0 and not is_terminal:
                entry["throughput_rows_per_sec"] = throughput

    return {
        "status": effective_status,
        "overall_percentage": round(overall_pct, 1),
        "tables_progress": tables_progress,
        "elapsed_seconds": elapsed,
        "estimated_remaining_seconds": eta,
        "throughput_rows_per_sec": throughput if not is_terminal else (
            total_rows_migrated / elapsed if elapsed > 0 else 0.0
        ),
        "total_rows_migrated": total_rows_migrated,
        "total_rows_estimate": total_rows_estimate,
    }


def list_jobs(project_id: str | None = None) -> list[tuple[UUID, MigrationJob]]:
    items = _registry.all_items()
    if project_id:
        items = [
            (jid, job)
            for jid, job in items
            if getattr(job, "project_id", None) == project_id
        ]
    return sorted(items, key=lambda pair: pair[1].created_at, reverse=True)


def cancel_all_tasks() -> list[asyncio.Task]:
    tasks = _registry.active_tasks()
    for t in tasks:
        t.cancel()
    return tasks


async def _resolve_masking_for_tables(
    source_entry: dict | None,
    *,
    tables: list[str],
    schema: str,
    masking_policy: str,
    column_transforms: dict[str, str] | None,
    column_sensitivity: dict[str, str] | None,
) -> dict[str, tuple[dict[str, str] | None, dict[str, str] | None, dict[str, str] | None]]:
    """Return per-table (transforms, sensitivity, column_types) for masking policies."""
    from domains.migration.masking_discovery import (
        TableMaskingProfile,
        discover_table_masking,
        merge_masking_profile,
    )

    per_table: dict[str, tuple[dict[str, str] | None, dict[str, str] | None, dict[str, str] | None]] = {}
    if masking_policy == "none":
        for table in tables:
            per_table[table] = (column_transforms, None, None)
        return per_table

    profiles: dict[str, TableMaskingProfile] = {}
    if source_entry:
        src_connector, _ = await make_connector(source_entry)
        await src_connector.connect()
        try:
            profiles = await discover_table_masking(
                src_connector,
                database=source_entry.get("database", ""),
                schema=schema,
                table_names=tables,
            )
        finally:
            await src_connector.disconnect()
    elif masking_policy == "strict":
        raise ValueError(
            "Strict masking requires source connection for PII discovery "
            "or explicit column_sensitivity map"
        )

    for table in tables:
        profile = profiles.get(
            table,
            TableMaskingProfile(
                table_name=table,
                column_sensitivity={},
                column_types={},
                sensitive_count=0,
            ),
        )
        transforms, sensitivity = merge_masking_profile(
            profile,
            masking_policy=masking_policy,
            column_transforms=column_transforms,
            column_sensitivity=column_sensitivity,
        )
        per_table[table] = (transforms, sensitivity, profile.column_types or None)
    return per_table


async def start_migration(
    source_connection_id: UUID,
    target_connection_id: UUID,
    tables: list[str],
    schema: str,
    strategy: MigrationStrategy,
    chunk_size: int,
    parallel_workers: int,
    *,
    target_schema: str | None = None,
    masking_policy: str = "none",
    column_transforms: dict[str, str] | None = None,
    column_sensitivity: dict[str, str] | None = None,
    require_target_snapshot: bool = True,
    snapshot_ref: str | None = None,
    idempotent: bool = False,
    validate_after: bool = True,
    table_policies: dict[str, str] | None = None,
    finalize_after: bool = True,
    finalize_options: dict[str, Any] | None = None,
    column_type_overrides: dict[str, str] | None = None,
    procedures: list[str] | None = None,
    functions: list[str] | None = None,
    migrate_procedural_after_tables: bool = True,
) -> MigrationJob:
    from apps.api.connection_store import get_entry
    from application.migration_settings_config import get_max_tables_per_job, resolved_source_throttle
    from application.go_engine_migration.target_table_preflight import (
        TargetTablePreflightError,
        inspect_target_tables,
        validate_table_policies,
    )
    from domains.migration.target_schema_resolver import resolve_target_schema

    resolved_target_schema = resolve_target_schema(schema, target_schema)

    max_tables = get_max_tables_per_job()
    if len(tables) > max_tables:
        raise ValueError(
            f"Cannot migrate more than {max_tables} tables in one job ({len(tables)} requested)"
        )

    from application.procedural_migration_service import build_initial_procedural_state

    procedural_state = build_initial_procedural_state(
        source_schema=schema,
        target_schema=resolved_target_schema,
        procedures=procedures,
        functions=functions,
        auto_migrate_after_tables=migrate_procedural_after_tables,
    )

    if not tables and not procedural_state.has_selection():
        raise ValueError(
            "Select at least one table or stored procedure/function to migrate"
        )

    procedural_only = not tables and procedural_state.has_selection()

    src_entry = get_entry(str(source_connection_id))
    masking_by_table = await _resolve_masking_for_tables(
        src_entry,
        tables=tables,
        schema=schema,
        masking_policy=masking_policy,
        column_transforms=column_transforms,
        column_sensitivity=column_sensitivity,
    )

    if require_target_snapshot or snapshot_ref:
        from domains.migration.snapshot_gate import SnapshotGate

        tgt_entry = get_entry(str(target_connection_id))
        if tgt_entry and tables:
            tgt_connector, _ = await make_connector(tgt_entry)
            await tgt_connector.connect()
            try:
                gate = SnapshotGate()
                snap = await gate.verify_or_create(
                    tgt_connector,
                    database=tgt_entry.get("database", "postgres"),
                    tables=tables,
                    schema=resolved_target_schema,
                    require_snapshot=require_target_snapshot,
                    existing_ref=snapshot_ref,
                )
                if not snap.verified:
                    raise ValueError(f"Target snapshot gate failed: {snap.message}")
                snapshot_ref = snap.snapshot_ref or snapshot_ref
            finally:
                await tgt_connector.disconnect()

    tgt_entry = get_entry(str(target_connection_id))
    if tgt_entry and tables:
        tgt_connector, _ = await make_connector(tgt_entry)
        await tgt_connector.connect()
        try:
            preflight = await inspect_target_tables(
                tgt_connector,
                target_schema=resolved_target_schema,
                table_names=tables,
                source_schema=schema,
            )
            validate_table_policies(preflight, table_policies)
        except TargetTablePreflightError:
            raise
        finally:
            await tgt_connector.disconnect()

    from domains.migration.go_engine.go_executor_kind import GoExecutorKind

    project_id = src_entry.get("project_id") if src_entry else None

    resolved_override_storage: dict[str, dict[str, Any]] = {}
    if column_type_overrides:
        from dataclasses import asdict

        from application.migration_readiness_service import assess_source_schema
        from apps.api.connection_store import get_decrypted_password
        from domains.migration.column_type_override import resolve_overrides_for_tables

        assessment = await assess_source_schema(
            src_entry,
            database=src_entry.get("database", ""),
            schema=schema,
            password=get_decrypted_password(src_entry),
        )
        resolved = resolve_overrides_for_tables(assessment, tables, column_type_overrides)
        resolved_override_storage = {k: asdict(v) for k, v in resolved.items()}

    job = MigrationJob(
        source_connection_id=source_connection_id,
        target_connection_id=target_connection_id,
        project_id=project_id,
        status=MigrationStatus.PENDING,
        tables=[
            TableMigrationPlan(
                table_name=t,
                schema_name=schema,
                target_schema=resolved_target_schema,
                columns=["*"],
                row_count_estimate=0,
                strategy=strategy,
                chunk_size=chunk_size,
                parallel_workers=parallel_workers,
                column_transforms=masking_by_table[t][0],
                column_sensitivity=masking_by_table[t][1],
                column_types=masking_by_table[t][2],
            )
            for t in tables
        ],
        idempotent_writes=idempotent,
        validate_after=validate_after,
        finalize_after=finalize_after,
        finalize_options=finalize_options,
        column_type_overrides=resolved_override_storage,
        procedural_migration=procedural_state.to_dict() if procedural_state else None,
    )
    job.snapshot_ref = snapshot_ref
    job.executor = GoExecutorKind.GO.value
    job.target_table_policies = table_policies or {}
    job.source_throttle = resolved_source_throttle()
    # Register + flip to RUNNING + record the task atomically so a concurrent
    # stop/list cannot observe a half-initialised job (Issue #1).
    async with _registry.lock:
        _registry.put(job)
        job.status = MigrationStatus.PENDING
    created_msg = (
        f"Procedural migration job created — "
        f"{len(procedural_state.selected_procedures)} procedure(s), "
        f"{len(procedural_state.selected_functions)} function(s) "
        f"from {schema} → {resolved_target_schema}"
        if procedural_only
        else f"Migration job created — {len(tables)} table(s) from {schema} → {resolved_target_schema}"
    )
    # Persist job row before logs — migration_job_logs FK requires migration_jobs.
    await save_jobs_async(force=True)
    await _append_job_log_durable(job.job_id, created_msg, level="info")
    await save_jobs_async()
    await _record_migration_audit(
        AuditAction.MIGRATION_STARTED,
        str(job.job_id),
        {
            "tables": tables,
            "schema": schema,
            "masking_policy": masking_policy,
            "snapshot_ref": snapshot_ref,
        },
        project_id=project_id,
    )
    notifier = create_notification_service()
    await notifier.job_started(str(job.job_id), tables or list(procedural_state.selected_procedures))
    if procedural_only:
        asyncio.create_task(_dispatch_procedural_only_migration_job(job.job_id))
    else:
        asyncio.create_task(_dispatch_go_migration_job(job.job_id))
    return job


async def _dispatch_procedural_only_migration_job(job_id: UUID) -> None:
    """Run stored procedure / function migration when no tables are selected."""
    from application.go_engine_migration.go_migration_job_watcher import _notify_terminal
    from application.procedural_migration_service import migrate_procedural_objects_for_job
    from domains.migration.procedural_migration_models import ProceduralMigrationPhaseStatus

    job = _registry.get(job_id)
    if not job:
        return

    async with _registry.lock:
        job.status = MigrationStatus.RUNNING
    await _persist_job_status(job_id, MigrationStatus.RUNNING)
    await save_jobs_async()
    await _append_job_log_durable(
        job_id,
        "Procedural-only migration — no tables selected; migrating routines directly",
        level="info",
    )

    try:
        result = await migrate_procedural_objects_for_job(job_id)
        if result.status in {
            ProceduralMigrationPhaseStatus.COMPLETED,
            ProceduralMigrationPhaseStatus.PARTIAL,
        }:
            job.status = MigrationStatus.COMPLETED
            await _persist_job_status(job_id, MigrationStatus.COMPLETED, set_completed_at=True)
        else:
            job.status = MigrationStatus.FAILED
            job.error_message = result.last_error or "Procedural migration failed"
            await _persist_job_status(
                job_id,
                MigrationStatus.FAILED,
                error=job.error_message,
                set_completed_at=True,
            )
    except Exception as exc:
        logger.error("procedural_only_migration_failed", job_id=str(job_id), error=str(exc))
        job.status = MigrationStatus.FAILED
        job.error_message = str(exc)[:500]
        await _persist_job_status(
            job_id,
            MigrationStatus.FAILED,
            error=job.error_message,
            set_completed_at=True,
        )
        await _append_job_log_durable(job_id, job.error_message, level="error")

    await save_jobs_async()
    await _notify_terminal(job_id, job)


async def _dispatch_go_migration_job(job_id: UUID) -> None:
    """Queue the job for the Go migration-engine (control plane only)."""
    from application.go_engine_migration.go_migration_job_dispatcher import (
        dispatch_migration_job_to_go_engine,
    )
    from application.go_engine_migration.go_migration_job_watcher import watch_go_migration_job

    job = _registry.get(job_id)
    validate_after = getattr(job, "validate_after", True) if job else True
    finalize_after = getattr(job, "finalize_after", True) if job else True

    await dispatch_migration_job_to_go_engine(job_id)
    await save_jobs_async()
    asyncio.create_task(
        watch_go_migration_job(
            job_id,
            validate_after=validate_after,
            finalize_after=finalize_after,
        )
    )


async def pause_job(job_id: UUID) -> MigrationJob:
    job = await refresh_job_from_metadata(job_id)
    if not job:
        raise KeyError(job_id)
    if job.status not in (MigrationStatus.RUNNING, MigrationStatus.QUEUED, MigrationStatus.RESUMED):
        raise ValueError(f"Job is not running (status={job.status.value})")

    async with AsyncSessionFactory() as session:
        from infrastructure.metadata_db.repositories.command_repository import CommandRepository
        await CommandRepository(session).issue(str(job_id), "PAUSE")

    await _persist_job_status(job_id, MigrationStatus.PAUSED)
    await _append_job_log_durable(job_id, "Migration pause requested — waiting for worker to acknowledge", level="info")
    await _record_migration_audit(
        AuditAction.MIGRATION_PAUSED,
        str(job_id),
        project_id=getattr(job, "project_id", None),
    )

    async with _registry.lock:
        job = _registry.get(job_id)
        if job:
            job.status = MigrationStatus.PAUSED
            job.updated_at = datetime.now(UTC)
    return job


async def resume_job(job_id: UUID) -> MigrationJob:
    job = await refresh_job_from_metadata(job_id)
    if not job:
        raise KeyError(job_id)
    if job.status != MigrationStatus.PAUSED:
        raise ValueError(f"Job is not paused (status={job.status.value})")

    async with AsyncSessionFactory() as session:
        from infrastructure.metadata_db.repositories.command_repository import CommandRepository
        await CommandRepository(session).issue(str(job_id), "RESUME")

    await _persist_job_status(job_id, MigrationStatus.RUNNING)
    await _append_job_log_durable(job_id, "Migration resume requested — worker will continue data movement", level="info")
    await _record_migration_audit(
        AuditAction.MIGRATION_RESUMED,
        str(job_id),
        project_id=getattr(job, "project_id", None),
    )

    async with _registry.lock:
        job = _registry.get(job_id)
        if job:
            job.status = MigrationStatus.RUNNING
            job.updated_at = datetime.now(UTC)
    return job


async def stop_job(job_id: UUID) -> MigrationJob:
    job = await refresh_job_from_metadata(job_id)
    project_id: str | None = None
    if job is None:
        async with AsyncSessionFactory() as session:
            record = await session.get(MigrationJobRecord, str(job_id))
        if record is None:
            raise KeyError(job_id)
        project_id = getattr(record, "project_id", None)
        try:
            db_status = MigrationStatus(record.status.lower())
        except ValueError:
            db_status = MigrationStatus.PENDING
        if db_status in _TERMINAL_STATUSES:
            return MigrationJob(
                job_id=job_id,
                source_connection_id=UUID(record.source_project_connection_id or "00000000-0000-0000-0000-000000000000"),
                target_connection_id=UUID(record.target_project_connection_id or "00000000-0000-0000-0000-000000000000"),
                status=db_status,
                project_id=project_id,
            )
    else:
        project_id = getattr(job, "project_id", None)
        if job.status in _TERMINAL_STATUSES:
            return job

    async with AsyncSessionFactory() as session:
        from infrastructure.metadata_db.repositories.command_repository import CommandRepository
        await CommandRepository(session).issue(str(job_id), "STOP")

    await _persist_job_status(job_id, MigrationStatus.STOPPED, set_completed_at=True)
    await _append_job_log_durable(job_id, "Migration stop requested — worker will halt after current chunk", level="warning")
    await _record_migration_audit(
        AuditAction.MIGRATION_STOPPED,
        str(job_id),
        project_id=project_id,
    )

    async with _registry.lock:
        job = _registry.get(job_id)
        if job:
            job.stop_requested = True
            job.status = MigrationStatus.STOPPED
            job.updated_at = datetime.now(UTC)
            return job

    return MigrationJob(
        job_id=job_id,
        source_connection_id=UUID(int=0),
        target_connection_id=UUID(int=0),
        status=MigrationStatus.STOPPED,
        project_id=project_id,
    )
