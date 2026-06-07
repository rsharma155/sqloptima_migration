"""
Module: go_migration_job_dispatcher.py
Purpose: Dispatch migration jobs to the Go data plane (no Python data movement).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete as sa_delete

from application.go_engine_migration.durable_migration_job_log_writer import (
    DurableMigrationJobLogWriter,
)
from application.go_engine_migration.go_job_dispatch_builder import GoJobDispatchBuilder
from application.go_engine_migration.go_migration_column_resolver import (
    resolve_source_table_column_types,
    resolve_source_table_columns,
)
from application.go_engine_migration.go_worker_health_checker import GoWorkerHealthChecker
from application.go_engine_migration.target_table_provisioner import provision_target_tables
from domains.migration.go_engine.go_executor_kind import GoExecutorKind
from domains.migration.go_engine.go_job_dispatch_config import GoJobDispatchConfig
from domains.migration.migration_engine import MigrationJob, MigrationStatus, MigrationStrategy
from infrastructure.metadata_db.models import MigrationJobRecord, MigrationTablePlanRecord
from infrastructure.metadata_db.repositories.command_repository import CommandRepository
from infrastructure.metadata_db.repositories.go_migration_job_queue_repository import (
    GoMigrationJobQueueRepository,
)
from infrastructure.metadata_db.session import AsyncSessionFactory
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


class GoMigrationJobDispatcher:
    """Prepares and queues a job for the Go migration-engine worker."""

    def __init__(
        self,
        *,
        dispatch_builder: GoJobDispatchBuilder | None = None,
        log_writer: DurableMigrationJobLogWriter | None = None,
        health_checker: GoWorkerHealthChecker | None = None,
        require_worker: bool = False,
    ) -> None:
        self._builder = dispatch_builder or GoJobDispatchBuilder()
        self._log_writer = log_writer or DurableMigrationJobLogWriter()
        self._health_checker = health_checker or GoWorkerHealthChecker()
        self._require_worker = require_worker

    async def dispatch(
        self,
        job: MigrationJob,
        *,
        source_entry: dict[str, Any],
        target_schema: str,
        snapshot_ref: str | None = None,
        idempotent: bool = False,
    ) -> GoJobDispatchConfig:
        from application.migration_service import make_connector
        from apps.api.connection_store import get_entry

        if self._require_worker:
            alive = await self._health_checker.is_worker_alive()
            if not alive:
                raise RuntimeError(
                    "Go migration-engine worker is not running (no recent heartbeat)"
                )

        source_schema = job.tables[0].schema_name if job.tables else "dbo"
        resolved: dict[str, list[str]] = {}

        tgt_entry = get_entry(str(job.target_connection_id))
        if not tgt_entry:
            raise RuntimeError("Target connection not found — cannot provision or dispatch migration")

        src_connector, _ = await make_connector(source_entry)
        tgt_connector, _ = await make_connector(tgt_entry)
        await src_connector.connect()
        await tgt_connector.connect()
        try:
            types_by_table = await resolve_source_table_column_types(
                src_connector,
                source_entry.get("database", ""),
                source_schema,
                [p.table_name for p in job.tables],
            )
            for plan in job.tables:
                resolved[plan.table_name] = await resolve_source_table_columns(
                    src_connector,
                    plan.schema_name,
                    plan.table_name,
                    plan.columns,
                )
                plan.columns = resolved[plan.table_name]
                plan.column_types = types_by_table.get(plan.table_name) or {}

            created_tables = await provision_target_tables(
                src_connector,
                tgt_connector,
                database=source_entry.get("database", ""),
                source_schema=source_schema,
                target_schema=target_schema,
                table_names=[p.table_name for p in job.tables],
            )
            if created_tables:
                msg = (
                    f"Provisioned {len(created_tables)} target table(s) in "
                    f"{target_schema}: {', '.join(created_tables)}"
                )
                await self._log_writer.append(str(job.job_id), msg, level="info")
        finally:
            await src_connector.disconnect()
            await tgt_connector.disconnect()

        dispatch = self._builder.build(
            job,
            source_schema=source_schema,
            target_schema=target_schema,
            resolved_columns_by_table=resolved,
            snapshot_ref=snapshot_ref,
            idempotent=idempotent,
        )

        async with AsyncSessionFactory() as session:
            queue_repo = GoMigrationJobQueueRepository(session)
            await queue_repo.save_dispatch_config(str(job.job_id), dispatch.to_dict())

            job_rec = await session.get(MigrationJobRecord, str(job.job_id))
            if job_rec:
                job_rec.tables_total = len(job.tables)
                job_rec.project_id = job.project_id
                job_rec.source_project_connection_id = str(job.source_connection_id)
                job_rec.target_project_connection_id = str(job.target_connection_id)
                await session.execute(
                    sa_delete(MigrationTablePlanRecord).where(
                        MigrationTablePlanRecord.migration_job_id == str(job.job_id)
                    )
                )
                for plan in job.tables:
                    session.add(
                        MigrationTablePlanRecord(
                            migration_job_id=str(job.job_id),
                            table_name=plan.table_name,
                            schema_name=plan.schema_name,
                            target_schema=plan.target_schema,
                            strategy=(
                                plan.strategy.value
                                if isinstance(plan.strategy, MigrationStrategy)
                                else str(plan.strategy)
                            ),
                            chunk_size=plan.chunk_size,
                            parallel_workers=plan.parallel_workers,
                            status="pending",
                            columns=plan.columns,
                            plan_config={
                                "column_transforms": plan.column_transforms,
                                "column_sensitivity": plan.column_sensitivity,
                                "column_types": plan.column_types,
                            },
                        )
                    )
                await session.commit()

            cmd_repo = CommandRepository(session)
            await cmd_repo.issue(str(job.job_id), "START")

        job.status = MigrationStatus.QUEUED
        job.executor = GoExecutorKind.GO.value
        job.dispatch_config = dispatch.to_dict()
        job.updated_at = datetime.now(UTC)

        msg = (
            f"Job queued for Go migration-engine — {len(job.tables)} table(s) "
            f"from {source_schema} → {target_schema}"
        )
        job.logs.append({
            "timestamp": datetime.now(UTC).isoformat(),
            "level": "info",
            "message": msg,
        })
        await self._log_writer.append(str(job.job_id), msg, level="info")

        logger.info(
            "migration_job_dispatched_to_go",
            job_id=str(job.job_id),
            source_db=source_entry.get("database"),
            target_db=tgt_entry.get("database") if tgt_entry else None,
            tables=[t.table_name for t in job.tables],
        )
        return dispatch


async def dispatch_migration_job_to_go_engine(job_id: UUID) -> None:
    """Entry point used by migration_service after job registration."""
    from application.migration_service import _registry
    from apps.api.connection_store import get_entry

    job = _registry.get(job_id)
    if not job:
        return

    src_entry = get_entry(str(job.source_connection_id))
    if not src_entry:
        job.status = MigrationStatus.FAILED
        job.error_message = "Migration aborted: source connection not found"
        return

    target_schema = job.tables[0].target_schema if job.tables else "public"
    dispatcher = GoMigrationJobDispatcher(require_worker=False)
    try:
        await dispatcher.dispatch(
            job,
            source_entry=src_entry,
            target_schema=target_schema,
            snapshot_ref=getattr(job, "snapshot_ref", None),
            idempotent=getattr(job, "idempotent_writes", False),
        )
    except Exception as exc:
        logger.error("go_migration_dispatch_failed", job_id=str(job_id), error=str(exc))
        job.status = MigrationStatus.FAILED
        job.error_message = str(exc)[:500]
        writer = DurableMigrationJobLogWriter()
        await writer.append(str(job_id), job.error_message, level="error")
