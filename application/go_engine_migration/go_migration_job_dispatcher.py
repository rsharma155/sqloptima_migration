"""
Module: go_migration_job_dispatcher.py
Purpose: Dispatch migration jobs to the Go data plane (no Python data movement).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from collections import defaultdict
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
from domains.migration.column_type_override import (
    ResolvedColumnTypeOverride,
    column_type_casts_for_plan,
    overrides_by_table,
)
from domains.migration.deferred_schema_catalog import (
    DeferredSchemaCatalogBuilder,
    catalog_to_dict,
)
from domains.migration.go_engine.go_executor_kind import GoExecutorKind
from domains.migration.go_engine.go_job_dispatch_config import GoJobDispatchConfig
from domains.migration.migration_engine import MigrationJob, MigrationStatus, MigrationStrategy
from domains.migration.target_schema_resolver import resolve_target_schema
from infrastructure.metadata_db.models import MigrationJobRecord, MigrationTablePlanRecord
from infrastructure.metadata_db.repositories.command_repository import CommandRepository
from infrastructure.metadata_db.repositories.go_migration_job_queue_repository import (
    GoMigrationJobQueueRepository,
)
from infrastructure.metadata_db.session import AsyncSessionFactory
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


def _load_resolved_overrides(job: MigrationJob) -> dict[str, ResolvedColumnTypeOverride]:
    raw = getattr(job, "column_type_overrides", None) or {}
    resolved: dict[str, ResolvedColumnTypeOverride] = {}
    for key, data in raw.items():
        if isinstance(data, ResolvedColumnTypeOverride):
            resolved[key] = data
        elif isinstance(data, dict):
            resolved[key] = ResolvedColumnTypeOverride(**data)
    return resolved


def _apply_column_type_overrides_to_plans(
    job: MigrationJob,
    resolved: dict[str, ResolvedColumnTypeOverride],
) -> dict[str, dict[str, str]]:
    """Apply user-approved type overrides to table plans; return PG DDL types per table."""
    by_table = overrides_by_table(resolved)
    pg_types_by_table: dict[str, dict[str, str]] = {}
    for plan in job.tables:
        table_overrides = by_table.get(plan.table_name, {})
        if not table_overrides:
            continue
        pg_types: dict[str, str] = {}
        extract_casts: dict[str, str] = {}
        column_types = dict(plan.column_types or {})
        for col, ro in table_overrides.items():
            column_types[col] = ro.extract_type
            extract_casts[col] = ro.source_cast_expression
            pg_types[col] = ro.load_pg_ddl_type
        plan.column_types = column_types
        plan.column_extract_casts = extract_casts
        pg_types_by_table[plan.table_name] = pg_types
    return pg_types_by_table


async def _fetch_source_row_count(
    source_connector: Any,
    source_schema: str,
    table_name: str,
) -> int:
    from infrastructure.sqlserver.row_count_estimate import (
        fetch_sqlserver_table_row_estimate,
    )

    try:
        return await fetch_sqlserver_table_row_estimate(
            source_connector, source_schema, table_name,
        )
    except Exception as exc:
        logger.warning(
            "source_row_count_failed",
            schema=source_schema,
            table=table_name,
            error=str(exc),
        )
        return 0


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
        policies = getattr(job, "target_table_policies", None) or {}

        tgt_entry = get_entry(str(job.target_connection_id))
        if not tgt_entry:
            raise RuntimeError("Target connection not found — cannot provision or dispatch migration")

        src_connector, _ = await make_connector(source_entry)
        tgt_connector, _ = await make_connector(tgt_entry)
        await src_connector.connect()
        await tgt_connector.connect()
        try:
            await self._log_writer.append(
                str(job.job_id),
                f"Preparing migration — resolving schema and row counts for {len(job.tables)} table(s)",
                level="info",
            )
            types_by_table = await resolve_source_table_column_types(
                src_connector,
                source_entry.get("database", ""),
                source_schema,
                [p.table_name for p in job.tables],
            )
            catalog_builder = DeferredSchemaCatalogBuilder(src_connector)
            total_row_estimate = 0
            deferred_by_table: dict[str, dict] = {}
            for plan in job.tables:
                plan.target_schema = resolve_target_schema(
                    plan.schema_name or source_schema,
                    plan.target_schema,
                )
                resolved[plan.table_name] = await resolve_source_table_columns(
                    src_connector,
                    plan.schema_name,
                    plan.table_name,
                    plan.columns,
                    database=source_entry.get("database", ""),
                )
                plan.columns = resolved[plan.table_name]
                plan.column_types = types_by_table.get(plan.table_name) or {}
                plan.row_count_estimate = await _fetch_source_row_count(
                    src_connector, plan.schema_name, plan.table_name,
                )
                from infrastructure.sqlserver.table_size_estimate import (
                    fetch_sqlserver_table_size_mb,
                )

                plan.table_size_mb = await fetch_sqlserver_table_size_mb(
                    src_connector, plan.schema_name, plan.table_name,
                )
            resolved_overrides = _load_resolved_overrides(job)
            pg_types_by_table = _apply_column_type_overrides_to_plans(job, resolved_overrides)
            for plan in job.tables:
                total_row_estimate += plan.row_count_estimate or 0
                src = plan.schema_name or source_schema
                tgt = plan.target_schema
                deferred_catalog = await catalog_builder.build_for_table(
                    src, plan.table_name, tgt,
                )
                deferred_by_table[plan.table_name] = catalog_to_dict(deferred_catalog)
                identity_count = len(deferred_catalog.identity_columns)
                index_count = len(deferred_catalog.secondary_indexes)
                if identity_count or index_count:
                    await self._log_writer.append(
                        str(job.job_id),
                        f"Deferred post-migration objects for {src}.{plan.table_name}: "
                        f"{identity_count} identity column(s), {index_count} secondary index(es)",
                        level="info",
                    )
                await self._log_writer.append(
                    str(job.job_id),
                    f"Source table {plan.schema_name}.{plan.table_name}: "
                    f"{plan.row_count_estimate or 0:,} row(s) estimated"
                    + (
                        f", ~{plan.table_size_mb:.1f} MB"
                        if (plan.table_size_mb or 0) > 0
                        else ""
                    ),
                    level="info",
                )

            provision_groups: dict[tuple[str, str], list[str]] = defaultdict(list)
            for plan in job.tables:
                src = plan.schema_name or source_schema
                tgt = plan.target_schema
                provision_groups[(src, tgt)].append(plan.table_name)

            created_tables: list[str] = []
            for (src_schema, tgt_schema), table_names in provision_groups.items():
                table_pg_types = {
                    name: pg_types_by_table[name]
                    for name in table_names
                    if name in pg_types_by_table
                }
                batch_created = await provision_target_tables(
                    src_connector,
                    tgt_connector,
                    database=source_entry.get("database", ""),
                    source_schema=src_schema,
                    target_schema=tgt_schema,
                    table_names=table_names,
                    table_policies=policies,
                    column_type_overrides_by_table=table_pg_types or None,
                )
                created_tables.extend(batch_created)
            if created_tables:
                schemas_used = sorted({tgt for _, tgt in provision_groups})
                msg = (
                    f"Provisioned {len(created_tables)} target table(s) in "
                    f"{', '.join(schemas_used)}: {', '.join(created_tables)}"
                )
                await self._log_writer.append(str(job.job_id), msg, level="info")
            for table_name, policy in policies.items():
                plan = next((p for p in job.tables if p.table_name == table_name), None)
                tgt_schema = plan.target_schema if plan else target_schema
                if policy == "truncate_reload":
                    await self._log_writer.append(
                        str(job.job_id),
                        f"Truncated existing target table {tgt_schema}.{table_name} before reload",
                        level="warning",
                    )
                elif policy == "drop_empty_recreate":
                    await self._log_writer.append(
                        str(job.job_id),
                        f"Recreated empty target table {tgt_schema}.{table_name}",
                        level="info",
                    )
        finally:
            await src_connector.disconnect()
            await tgt_connector.disconnect()

        dispatch = self._builder.build(
            job,
            source_schema=source_schema,
            target_schema=job.tables[0].target_schema if job.tables else target_schema,
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
                job_rec.rows_total = total_row_estimate
                job_rec.project_id = job.project_id
                job_rec.source_project_connection_id = str(job.source_connection_id)
                job_rec.target_project_connection_id = str(job.target_connection_id)
                existing_config = dict(job_rec.config or {})
                if getattr(job, "finalize_options", None):
                    existing_config["finalize_options"] = job.finalize_options
                if getattr(job, "procedural_migration", None):
                    existing_config["procedural_migration"] = job.procedural_migration
                job_rec.config = existing_config
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
                            row_count_estimate=plan.row_count_estimate or 0,
                            columns=plan.columns,
                            plan_config={
                                "column_transforms": plan.column_transforms,
                                "column_sensitivity": plan.column_sensitivity,
                                "column_types": plan.column_types,
                                "column_extract_casts": plan.column_extract_casts,
                                "column_type_casts": column_type_casts_for_plan(
                                    resolved_overrides, plan.table_name,
                                ),
                                "deferred_schema": deferred_by_table.get(plan.table_name),
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

        resolved_target = job.tables[0].target_schema if job.tables else target_schema
        msg = (
            f"Job queued for Go migration-engine — {len(job.tables)} table(s) "
            f"from {source_schema} → {resolved_target}"
        )
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

    first_plan = job.tables[0] if job.tables else None
    source_schema = first_plan.schema_name if first_plan else "dbo"
    target_schema = resolve_target_schema(
        source_schema,
        first_plan.target_schema if first_plan else None,
    )
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
