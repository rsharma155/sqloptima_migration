"""
Module: go_migration_job_watcher.py
Purpose: Poll metadata for Go job completion and run post-migration validation.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import asyncio
import time
from uuid import UUID

from domains.migration.migration_engine import MigrationStatus
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

_TERMINAL_STATUSES = frozenset({
    MigrationStatus.COMPLETED,
    MigrationStatus.PARTIAL,
    MigrationStatus.FAILED,
    MigrationStatus.STOPPED,
})

DEFAULT_POLL_INTERVAL_SEC = 3.0
DEFAULT_WATCH_TIMEOUT_SEC = 3600.0


async def watch_go_migration_job(
    job_id: UUID,
    *,
    validate_after: bool = True,
    finalize_after: bool = True,
    poll_interval_sec: float = DEFAULT_POLL_INTERVAL_SEC,
    timeout_sec: float = DEFAULT_WATCH_TIMEOUT_SEC,
) -> None:
    """Poll durable job status until terminal; validate and finalize when configured."""
    from application import migration_service as svc

    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        job = await svc.refresh_job_from_metadata(job_id)
        if job is None:
            logger.warning("go_job_watcher_missing_job", job_id=str(job_id))
            return
        if job.status in _TERMINAL_STATUSES:
            await _notify_terminal(job_id, job)
            validation_ok = True
            if validate_after and job.status in (MigrationStatus.COMPLETED, MigrationStatus.PARTIAL):
                validation_ok = await _run_post_migration_validation(job_id, job)
            if (
                finalize_after
                and job.status in (MigrationStatus.COMPLETED, MigrationStatus.PARTIAL)
                and validation_ok
            ):
                await _run_post_migration_finalize(job_id, job)
            if job.status in (MigrationStatus.COMPLETED, MigrationStatus.PARTIAL) and validation_ok:
                await _run_procedural_migration(job_id, job)
            return
        await asyncio.sleep(poll_interval_sec)

    logger.warning("go_job_watcher_timeout", job_id=str(job_id), timeout_sec=timeout_sec)


async def _notify_terminal(job_id: UUID, job: object) -> None:
    """Fire audit + alert hooks when the Go worker reaches a terminal status."""
    from application.migration_service import _record_migration_audit
    from application.notification_service import create_notification_service
    from shared.security.audit_log import AuditAction

    status = getattr(job, "status", None)
    rows = sum(getattr(t, "rows_migrated", 0) for t in getattr(job, "tables", []))
    notifier = create_notification_service()
    project_id = getattr(job, "project_id", None)

    if status == MigrationStatus.COMPLETED:
        await _record_migration_audit(
            AuditAction.MIGRATION_COMPLETED,
            str(job_id),
            {"rows_migrated": rows},
            project_id=project_id,
        )
        await notifier.job_completed(str(job_id), status.value, rows)
    elif status == MigrationStatus.PARTIAL:
        error = getattr(job, "error_message", None) or "one or more tables failed"
        await _record_migration_audit(
            AuditAction.MIGRATION_COMPLETED,
            str(job_id),
            {"rows_migrated": rows, "partial": True},
            project_id=project_id,
            success=True,
            error_message=error,
        )
        await notifier.job_completed(str(job_id), status.value, rows)
    elif status == MigrationStatus.FAILED:
        error = getattr(job, "error_message", None) or "unknown error"
        await _record_migration_audit(
            AuditAction.MIGRATION_FAILED,
            str(job_id),
            success=False,
            error_message=error,
            project_id=project_id,
        )
        await notifier.job_failed(str(job_id), error)


async def _run_post_migration_validation(job_id: UUID, job: object) -> bool:
    from application.migration_service import _append_job_log_durable, get_job

    from domains.migration.target_schema_resolver import resolve_target_schema
    from domains.orchestration.activities import validate_table

    job = get_job(job_id) or job

    source_id = str(getattr(job, "source_connection_id"))
    target_id = str(getattr(job, "target_connection_id"))
    tables = getattr(job, "tables", [])
    if not tables:
        return True

    passed = 0
    failed = 0

    for plan in tables:
        if (plan.status or "").lower() == "failed":
            continue
        schema = plan.schema_name or "dbo"
        target_schema = resolve_target_schema(schema, plan.target_schema)
        result = await validate_table(
            source_id, target_id, schema, plan.table_name, target_schema=target_schema,
            expected_row_count=plan.rows_migrated if (plan.rows_migrated or 0) > 0 else None,
        )
        if result.get("status") == "passed":
            passed += 1
            await _append_job_log_durable(
                job_id,
                f"Validation passed for {plan.table_name}: "
                f"{result.get('source_count')} source / {result.get('target_count')} target rows",
                level="success",
            )
        else:
            failed += 1
            await _append_job_log_durable(
                job_id,
                f"Validation failed for {plan.table_name}: {result}",
                level="error",
            )

    logger.info(
        "go_job_post_validation_complete",
        job_id=str(job_id),
        passed=passed,
        failed=failed,
    )
    return failed == 0


async def _run_post_migration_finalize(job_id: UUID, job: object) -> None:
    from application.go_engine_migration.post_migration_finalizer import finalize_migration_job
    from application.migration_service import _append_job_log_durable
    from domains.migration.post_migration_finalize_models import (
        FinalizePhaseStatus,
        PostMigrationFinalizeOptions,
    )

    options_data = getattr(job, "finalize_options", None) or {}
    options = PostMigrationFinalizeOptions.from_dict(options_data)
    if not options.auto_finalize_after_validation:
        await _append_job_log_durable(
            job_id,
            "Post-migration finalize skipped — auto_finalize_after_validation is disabled",
            level="info",
        )
        return

    await _append_job_log_durable(
        job_id,
        "Starting post-migration finalize (identity, indexes, constraints, defaults)",
        level="info",
    )
    state = await finalize_migration_job(job_id, options=options)
    if state.status == FinalizePhaseStatus.COMPLETED:
        await _append_job_log_durable(
            job_id,
            "Post-migration finalize completed successfully",
            level="success",
        )
    elif state.status == FinalizePhaseStatus.PARTIAL:
        await _append_job_log_durable(
            job_id,
            "Post-migration finalize completed with some failures — review finalize status",
            level="warning",
        )
    else:
        await _append_job_log_durable(
            job_id,
            f"Post-migration finalize failed: {state.last_error or state.status.value}",
            level="error",
        )
    logger.info(
        "go_job_post_finalize_complete",
        job_id=str(job_id),
        status=state.status.value,
    )


async def _run_procedural_migration(job_id: UUID, job: object) -> None:
    from application.migration_service import _append_job_log_durable
    from application.procedural_migration_service import migrate_procedural_objects_for_job
    from domains.migration.procedural_migration_models import ProceduralMigrationState

    proc_cfg = getattr(job, "procedural_migration", None)
    if not proc_cfg:
        return
    state = ProceduralMigrationState.from_dict(proc_cfg)
    if not state.has_selection():
        return
    if not state.auto_migrate_after_tables:
        await _append_job_log_durable(
            job_id,
            "Procedural migration skipped — auto_migrate_after_tables is disabled",
            level="info",
        )
        return

    await _append_job_log_durable(
        job_id,
        "Starting stored procedure / function migration to PostgreSQL",
        level="info",
    )
    result = await migrate_procedural_objects_for_job(job_id)
    if result.status.value == "completed":
        await _append_job_log_durable(
            job_id,
            "Stored procedure / function migration completed successfully",
            level="success",
        )
    elif result.status.value == "partial":
        await _append_job_log_durable(
            job_id,
            "Stored procedure / function migration completed with failures — review procedural status",
            level="warning",
        )
    elif result.status.value != "skipped":
        await _append_job_log_durable(
            job_id,
            f"Stored procedure / function migration failed: {result.last_error or result.status.value}",
            level="error",
        )
    logger.info(
        "go_job_procedural_migration_complete",
        job_id=str(job_id),
        status=result.status.value,
    )
