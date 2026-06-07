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
from application.notification_service import NotificationService
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
    MigrationStatus.FAILED,
    MigrationStatus.STOPPED,
})
_TERMINAL_DB_STATUSES = frozenset({"completed", "failed", "stopped"})
_COMPLETED_TABLE_STATUSES = frozenset({"completed", "done"})

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


def _append_job_log(job: MigrationJob, message: str, *, level: str = "info") -> None:
    job.logs.append({
        "timestamp": datetime.now(UTC).isoformat(),
        "level": level,
        "message": message,
    })


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
        except ValueError:
            pass

    # Honor terminal status already merged onto the in-memory job (e.g. FAILED from DB).
    if job.status in _TERMINAL_STATUSES:
        return job.status

    if not job.tables:
        return job.status

    table_statuses = [(t.status or "").lower() for t in job.tables]
    if any(s == "failed" for s in table_statuses):
        return MigrationStatus.FAILED
    if table_statuses and all(s in _COMPLETED_TABLE_STATUSES for s in table_statuses):
        return MigrationStatus.COMPLETED
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


async def save_jobs_async() -> None:
    """Upsert all in-memory jobs to the metadata DB (debounced to 2 s)."""
    global _jobs_last_save, _jobs_dirty
    now = datetime.now(UTC).timestamp()
    if now - _jobs_last_save < _JOBS_SAVE_INTERVAL:
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
                if executor == "go" and existing is not None:
                    db_status = (existing.status or "").lower()
                    if db_status in _TERMINAL_DB_STATUSES:
                        status_value = existing.status
                    job_rec = MigrationJobRecord(
                        migration_job_id=str(jid),
                        source_project_connection_id=str(job.source_connection_id),
                        target_project_connection_id=str(job.target_connection_id),
                        status=status_value,
                        error=getattr(job, "error_message", None),
                        project_id=getattr(job, "project_id", None) or existing.project_id,
                        config=getattr(job, "dispatch_config", None) or existing.config,
                        executor=executor,
                        tables_total=existing.tables_total or len(job.tables),
                        tables_done=existing.tables_done,
                        rows_total=existing.rows_total,
                        rows_migrated=existing.rows_migrated,
                        started_at=existing.started_at or getattr(job, "started_at", None),
                        completed_at=existing.completed_at,
                        created_at=existing.created_at,
                        updated_at=job.updated_at if hasattr(job, "updated_at") else datetime.now(UTC),
                    )
                    await session.merge(job_rec)
                    continue

                job_rec = MigrationJobRecord(
                    migration_job_id=str(jid),
                    source_project_connection_id=str(job.source_connection_id),
                    target_project_connection_id=str(job.target_connection_id),
                    status=status_value,
                    error=getattr(job, "error_message", None),
                    project_id=getattr(job, "project_id", None),
                    config=getattr(job, "dispatch_config", None),
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
            PostgresConnectionConfig, PostgresConnector,
        )
        config = PostgresConnectionConfig(
            host=entry["host"],
            port=int(entry.get("port", 5432)),
            database=entry["database"],
            username=entry.get("username", ""),
            password=password,
            schema=entry.get("schema", "public"),
        )
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
    except Exception as exc:
        logger.warning("Failed to refresh job from metadata", job_id=str(job_id), error=str(exc))
        return job

    if record is None:
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
    target_schema: str = "public",
    masking_policy: str = "none",
    column_transforms: dict[str, str] | None = None,
    column_sensitivity: dict[str, str] | None = None,
    require_target_snapshot: bool = True,
    snapshot_ref: str | None = None,
    idempotent: bool = False,
    validate_after: bool = True,
) -> MigrationJob:
    from apps.api.connection_store import get_entry

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
        if tgt_entry:
            tgt_connector, _ = await make_connector(tgt_entry)
            await tgt_connector.connect()
            try:
                gate = SnapshotGate()
                snap = await gate.verify_or_create(
                    tgt_connector,
                    database=tgt_entry.get("database", "postgres"),
                    tables=tables,
                    schema=target_schema,
                    require_snapshot=require_target_snapshot,
                    existing_ref=snapshot_ref,
                )
                if not snap.verified:
                    raise ValueError(f"Target snapshot gate failed: {snap.message}")
                snapshot_ref = snap.snapshot_ref or snapshot_ref
            finally:
                await tgt_connector.disconnect()

    from domains.migration.go_engine.go_executor_kind import GoExecutorKind

    project_id = src_entry.get("project_id") if src_entry else None

    job = MigrationJob(
        source_connection_id=source_connection_id,
        target_connection_id=target_connection_id,
        project_id=project_id,
        status=MigrationStatus.PENDING,
        tables=[
            TableMigrationPlan(
                table_name=t,
                schema_name=schema,
                target_schema=target_schema,
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
    )
    job.snapshot_ref = snapshot_ref
    job.executor = GoExecutorKind.GO.value
    # Register + flip to RUNNING + record the task atomically so a concurrent
    # stop/list cannot observe a half-initialised job (Issue #1).
    async with _registry.lock:
        _registry.put(job)
        job.status = MigrationStatus.PENDING
    _append_job_log(
        job,
        f"Migration job created — {len(tables)} table(s) from {schema} → {target_schema}",
    )
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
    notifier = NotificationService()
    await notifier.job_started(str(job.job_id), tables)
    asyncio.create_task(_dispatch_go_migration_job(job.job_id))
    return job


async def _dispatch_go_migration_job(job_id: UUID) -> None:
    """Queue the job for the Go migration-engine (control plane only)."""
    from application.go_engine_migration.go_migration_job_dispatcher import (
        dispatch_migration_job_to_go_engine,
    )
    from application.go_engine_migration.go_migration_job_watcher import watch_go_migration_job

    job = _registry.get(job_id)
    validate_after = getattr(job, "validate_after", True) if job else True

    await dispatch_migration_job_to_go_engine(job_id)
    await save_jobs_async()
    asyncio.create_task(watch_go_migration_job(job_id, validate_after=validate_after))


async def pause_job(job_id: UUID) -> MigrationJob:
    async with _registry.lock:
        job = _registry.get(job_id)
        if not job:
            raise KeyError(job_id)
        if job.status not in (MigrationStatus.RUNNING, MigrationStatus.QUEUED):
            raise ValueError(f"Job is not running (status={job.status})")
        job.status = MigrationStatus.PAUSED
        job.updated_at = datetime.now(UTC)
    async with AsyncSessionFactory() as session:
        from infrastructure.metadata_db.repositories.command_repository import CommandRepository
        await CommandRepository(session).issue(str(job_id), "PAUSE")
    await save_jobs_async()
    return job


async def resume_job(job_id: UUID) -> MigrationJob:
    async with _registry.lock:
        job = _registry.get(job_id)
        if not job:
            raise KeyError(job_id)
        if job.status != MigrationStatus.PAUSED:
            raise ValueError(f"Job is not paused (status={job.status})")
        job.status = MigrationStatus.RUNNING
        job.updated_at = datetime.now(UTC)
    async with AsyncSessionFactory() as session:
        from infrastructure.metadata_db.repositories.command_repository import CommandRepository
        await CommandRepository(session).issue(str(job_id), "RESUME")
    await save_jobs_async()
    return job


async def stop_job(job_id: UUID) -> MigrationJob:
    async with _registry.lock:
        job = _registry.get(job_id)
        if not job:
            raise KeyError(job_id)
        job.stop_requested = True
        job.status = MigrationStatus.STOPPED
        job.updated_at = datetime.now(UTC)
    async with AsyncSessionFactory() as session:
        from infrastructure.metadata_db.repositories.command_repository import CommandRepository
        await CommandRepository(session).issue(str(job_id), "STOP")
    await save_jobs_async()
    return job
