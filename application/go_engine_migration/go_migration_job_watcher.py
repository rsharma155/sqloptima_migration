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
    MigrationStatus.FAILED,
    MigrationStatus.STOPPED,
})

DEFAULT_POLL_INTERVAL_SEC = 3.0
DEFAULT_WATCH_TIMEOUT_SEC = 3600.0


async def watch_go_migration_job(
    job_id: UUID,
    *,
    validate_after: bool = True,
    poll_interval_sec: float = DEFAULT_POLL_INTERVAL_SEC,
    timeout_sec: float = DEFAULT_WATCH_TIMEOUT_SEC,
) -> None:
    """Poll durable job status until terminal; optionally validate row counts."""
    from application import migration_service as svc

    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        job = await svc.refresh_job_from_metadata(job_id)
        if job is None:
            logger.warning("go_job_watcher_missing_job", job_id=str(job_id))
            return
        if job.status in _TERMINAL_STATUSES:
            await _notify_terminal(job_id, job)
            if validate_after and job.status == MigrationStatus.COMPLETED:
                await _run_post_migration_validation(job_id, job)
            return
        await asyncio.sleep(poll_interval_sec)

    logger.warning("go_job_watcher_timeout", job_id=str(job_id), timeout_sec=timeout_sec)


async def _notify_terminal(job_id: UUID, job: object) -> None:
    """Fire audit + alert hooks when the Go worker reaches a terminal status."""
    from application.migration_service import _record_migration_audit
    from application.notification_service import NotificationService
    from shared.security.audit_log import AuditAction

    status = getattr(job, "status", None)
    rows = sum(getattr(t, "rows_migrated", 0) for t in getattr(job, "tables", []))
    notifier = NotificationService()
    project_id = getattr(job, "project_id", None)

    if status == MigrationStatus.COMPLETED:
        await _record_migration_audit(
            AuditAction.MIGRATION_COMPLETED,
            str(job_id),
            {"rows_migrated": rows},
            project_id=project_id,
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


async def _run_post_migration_validation(job_id: UUID, job: object) -> None:
    from application.migration_service import _append_job_log, get_job, save_jobs_async
    from domains.orchestration.activities import validate_table

    job = get_job(job_id) or job

    source_id = str(getattr(job, "source_connection_id"))
    target_id = str(getattr(job, "target_connection_id"))
    tables = getattr(job, "tables", [])
    if not tables:
        return

    schema = tables[0].schema_name or "dbo"
    target_schema = tables[0].target_schema or "public"
    passed = 0
    failed = 0

    for plan in tables:
        result = await validate_table(
            source_id, target_id, schema, plan.table_name, target_schema=target_schema,
        )
        if result.get("status") == "passed":
            passed += 1
            _append_job_log(
                job,
                f"Validation passed for {plan.table_name}: "
                f"{result.get('source_count')} source / {result.get('target_count')} target rows",
                level="success",
            )
        else:
            failed += 1
            _append_job_log(
                job,
                f"Validation failed for {plan.table_name}: {result}",
                level="error",
            )

    from application.migration_service import save_jobs_async

    await save_jobs_async()
    logger.info(
        "go_job_post_validation_complete",
        job_id=str(job_id),
        passed=passed,
        failed=failed,
        target_schema=target_schema,
    )
