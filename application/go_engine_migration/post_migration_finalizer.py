"""
Module: post_migration_finalizer.py
Purpose: Apply deferred PostgreSQL schema objects after successful data migration.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from domains.migration.deferred_schema_catalog import (
    DeferredTableSchema,
    catalog_from_dict,
)
from domains.migration.post_migration_ddl_generator import PostMigrationDdlGenerator
from domains.migration.post_migration_finalize_models import (
    FinalizeObjectResult,
    FinalizeObjectStatus,
    FinalizePhaseStatus,
    FinalizeTableResult,
    PostMigrationFinalizeOptions,
    PostMigrationFinalizeState,
)
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

_EMPTY_INVENTORY: dict[str, Any] = {
    "identities": [],
    "indexes": [],
    "foreign_keys": [],
    "check_constraints": [],
    "defaults": [],
    "triggers": [],
}


class PostMigrationFinalizer:
    """Execute post-migration DDL in a safe, ordered sequence per table."""

    def __init__(
        self,
        target_connector: Any,
        *,
        ddl_generator: PostMigrationDdlGenerator | None = None,
    ) -> None:
        self._connector = target_connector
        self._ddl = ddl_generator or PostMigrationDdlGenerator()

    async def finalize_table(
        self,
        catalog: DeferredTableSchema,
        *,
        options: PostMigrationFinalizeOptions | None = None,
        schema_map: dict[str, str] | None = None,
        column_type_casts: list[dict[str, str]] | None = None,
    ) -> FinalizeTableResult:
        opts = options or PostMigrationFinalizeOptions()
        schema_resolver = {k.lower(): v for k, v in (schema_map or {}).items()}
        result = FinalizeTableResult(
            table_name=catalog.table_name,
            target_schema=catalog.target_schema,
        )
        failures = 0

        for cast in column_type_casts or []:
            obj = await self._apply_column_type_cast(catalog, cast)
            result.objects.append(obj)
            if obj.status == FinalizeObjectStatus.FAILED:
                failures += 1

        if opts.finalize_identities:
            for col in catalog.identity_columns:
                obj = await self._apply_identity(catalog, col)
                result.objects.append(obj)
                if obj.status == FinalizeObjectStatus.FAILED:
                    failures += 1

        if opts.finalize_indexes:
            for idx in catalog.secondary_indexes:
                obj = await self._apply_index(
                    catalog, idx, concurrently=opts.create_indexes_concurrently,
                )
                result.objects.append(obj)
                if obj.status == FinalizeObjectStatus.FAILED:
                    failures += 1

        if opts.finalize_foreign_keys:
            for fk in catalog.foreign_keys:
                obj = await self._apply_foreign_key(catalog, fk, schema_resolver)
                result.objects.append(obj)
                if obj.status == FinalizeObjectStatus.FAILED:
                    failures += 1

        if opts.finalize_check_constraints:
            for chk in catalog.check_constraints:
                obj = await self._apply_check(catalog, chk)
                result.objects.append(obj)
                if obj.status == FinalizeObjectStatus.FAILED:
                    failures += 1

        if opts.finalize_defaults:
            for default in catalog.column_defaults:
                obj = await self._apply_default(catalog, default)
                result.objects.append(obj)
                if obj.status == FinalizeObjectStatus.FAILED:
                    failures += 1

        if opts.finalize_triggers:
            for trigger in catalog.triggers:
                obj = FinalizeObjectResult(
                    object_key=trigger.trigger_name,
                    object_type="trigger",
                    status=FinalizeObjectStatus.SKIPPED,
                    message="Trigger conversion requires manual review — not auto-applied",
                )
                result.objects.append(obj)

        if failures:
            result.status = FinalizePhaseStatus.PARTIAL
        else:
            result.status = FinalizePhaseStatus.COMPLETED
        return result

    async def _execute_statements(self, statements: list[str]) -> None:
        for stmt in statements:
            await self._connector.execute(stmt)

    async def _apply_identity(
        self,
        catalog: DeferredTableSchema,
        col: Any,
    ) -> FinalizeObjectResult:
        key = col.column_name
        stmts = self._ddl.generate_identity_finalize(
            catalog.target_schema, catalog.table_name, col,
        )
        try:
            await self._execute_statements(stmts)
            return FinalizeObjectResult(
                object_key=key,
                object_type="identity",
                status=FinalizeObjectStatus.APPLIED,
                ddl="\n".join(stmts),
            )
        except Exception as exc:
            logger.warning(
                "finalize_identity_failed",
                table=catalog.table_name,
                column=key,
                error=str(exc),
            )
            return FinalizeObjectResult(
                object_key=key,
                object_type="identity",
                status=FinalizeObjectStatus.FAILED,
                message=str(exc),
            )

    async def _apply_column_type_cast(
        self,
        catalog: DeferredTableSchema,
        cast: dict[str, str],
    ) -> FinalizeObjectResult:
        column_name = str(cast["column_name"])
        final_type = str(cast["final_pg_type"])
        using_sql = str(cast["using_sql"])
        key = f"type_cast:{column_name}"
        stmt = self._ddl.generate_column_type_cast(
            catalog.target_schema,
            catalog.table_name,
            column_name,
            final_type,
            using_sql,
        )
        try:
            await self._execute_statements([stmt])
            return FinalizeObjectResult(
                object_key=key,
                object_type="column_type_cast",
                status=FinalizeObjectStatus.APPLIED,
                ddl=stmt,
                message=f"{cast.get('load_pg_type', 'text')} → {final_type}",
            )
        except Exception as exc:
            logger.warning(
                "finalize_column_type_cast_failed",
                table=catalog.table_name,
                column=column_name,
                error=str(exc),
            )
            return FinalizeObjectResult(
                object_key=key,
                object_type="column_type_cast",
                status=FinalizeObjectStatus.FAILED,
                message=str(exc),
                ddl=stmt,
            )

    async def _apply_index(
        self,
        catalog: DeferredTableSchema,
        idx: Any,
        *,
        concurrently: bool,
    ) -> FinalizeObjectResult:
        if idx.unsupported_reason:
            return FinalizeObjectResult(
                object_key=idx.index_name,
                object_type="index",
                status=FinalizeObjectStatus.UNSUPPORTED,
                message=f"Unsupported index type: {idx.unsupported_reason}",
            )
        ddl = self._ddl.generate_secondary_index(
            catalog.target_schema,
            catalog.table_name,
            idx,
            concurrently=concurrently,
        )
        if not ddl:
            return FinalizeObjectResult(
                object_key=idx.index_name,
                object_type="index",
                status=FinalizeObjectStatus.SKIPPED,
                message="No DDL generated",
            )
        try:
            await self._connector.execute(ddl)
            return FinalizeObjectResult(
                object_key=idx.index_name,
                object_type="index",
                status=FinalizeObjectStatus.APPLIED,
                ddl=ddl,
            )
        except Exception as exc:
            return FinalizeObjectResult(
                object_key=idx.index_name,
                object_type="index",
                status=FinalizeObjectStatus.FAILED,
                message=str(exc),
                ddl=ddl,
            )

    async def _apply_foreign_key(
        self,
        catalog: DeferredTableSchema,
        fk: Any,
        schema_resolver: dict[str, str],
    ) -> FinalizeObjectResult:
        stmts = self._ddl.generate_foreign_key(
            catalog.target_schema,
            catalog.table_name,
            fk,
            target_schema_resolver=schema_resolver,
        )
        if not stmts:
            return FinalizeObjectResult(
                object_key=fk.constraint_name,
                object_type="foreign_key",
                status=FinalizeObjectStatus.SKIPPED,
                message="Disabled or incomplete FK metadata",
            )
        try:
            await self._execute_statements(stmts)
            return FinalizeObjectResult(
                object_key=fk.constraint_name,
                object_type="foreign_key",
                status=FinalizeObjectStatus.APPLIED,
                ddl="\n".join(stmts),
            )
        except Exception as exc:
            return FinalizeObjectResult(
                object_key=fk.constraint_name,
                object_type="foreign_key",
                status=FinalizeObjectStatus.FAILED,
                message=str(exc),
            )

    async def _apply_check(
        self,
        catalog: DeferredTableSchema,
        chk: Any,
    ) -> FinalizeObjectResult:
        stmts = self._ddl.generate_check_constraint(
            catalog.target_schema, catalog.table_name, chk,
        )
        if not stmts:
            return FinalizeObjectResult(
                object_key=chk.constraint_name,
                object_type="check",
                status=FinalizeObjectStatus.SKIPPED,
            )
        try:
            await self._execute_statements(stmts)
            return FinalizeObjectResult(
                object_key=chk.constraint_name,
                object_type="check",
                status=FinalizeObjectStatus.APPLIED,
                ddl="\n".join(stmts),
            )
        except Exception as exc:
            return FinalizeObjectResult(
                object_key=chk.constraint_name,
                object_type="check",
                status=FinalizeObjectStatus.FAILED,
                message=str(exc),
            )

    async def _apply_default(
        self,
        catalog: DeferredTableSchema,
        default: Any,
    ) -> FinalizeObjectResult:
        ddl = self._ddl.generate_column_default(
            catalog.target_schema, catalog.table_name, default,
        )
        if not ddl:
            return FinalizeObjectResult(
                object_key=default.column_name,
                object_type="default",
                status=FinalizeObjectStatus.SKIPPED,
                message="Default expression not auto-transpilable",
            )
        try:
            await self._connector.execute(ddl)
            return FinalizeObjectResult(
                object_key=default.column_name,
                object_type="default",
                status=FinalizeObjectStatus.APPLIED,
                ddl=ddl,
            )
        except Exception as exc:
            return FinalizeObjectResult(
                object_key=default.column_name,
                object_type="default",
                status=FinalizeObjectStatus.FAILED,
                message=str(exc),
            )


async def finalize_migration_job(
    job_id: UUID,
    *,
    options: PostMigrationFinalizeOptions | None = None,
) -> PostMigrationFinalizeState:
    """Finalize all tables for a completed migration job."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from application.migration_service import make_connector
    from apps.api.connection_store import get_entry
    from infrastructure.metadata_db.models import MigrationJobRecord
    from infrastructure.metadata_db.session import AsyncSessionFactory

    opts = options or PostMigrationFinalizeOptions()
    state = PostMigrationFinalizeState(status=FinalizePhaseStatus.IN_PROGRESS)

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(MigrationJobRecord)
            .where(MigrationJobRecord.migration_job_id == str(job_id))
            .options(selectinload(MigrationJobRecord.table_plans))
        )
        job_rec = result.scalar_one_or_none()
        if not job_rec:
            state.status = FinalizePhaseStatus.FAILED
            state.last_error = "Job not found"
            return state

        config = dict(job_rec.config or {})
        config["post_migration_finalize"] = state.to_dict()
        config["finalize_options"] = opts.to_dict()
        job_rec.config = config
        await session.commit()

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(MigrationJobRecord)
            .where(MigrationJobRecord.migration_job_id == str(job_id))
            .options(selectinload(MigrationJobRecord.table_plans))
        )
        job_rec = result.scalar_one_or_none()
        if not job_rec:
            state.status = FinalizePhaseStatus.FAILED
            state.last_error = "Job not found"
            return state

        tgt_entry = get_entry(str(job_rec.target_project_connection_id or ""))
        if not tgt_entry:
            state.status = FinalizePhaseStatus.FAILED
            state.last_error = "Target connection not found"
            config = dict(job_rec.config or {})
            config["post_migration_finalize"] = state.to_dict()
            job_rec.config = config
            await session.commit()
            return state

        tgt_connector, _ = await make_connector(tgt_entry)
        await tgt_connector.connect()
        finalizer = PostMigrationFinalizer(tgt_connector)
        schema_map: dict[str, str] = {}
        failures = 0

        try:
            for plan in job_rec.table_plans:
                cfg = plan.plan_config or {}
                deferred = cfg.get("deferred_schema")
                casts = cfg.get("column_type_casts") or []
                if not deferred and not casts:
                    continue
                if deferred:
                    catalog = catalog_from_dict(deferred)
                else:
                    catalog = DeferredTableSchema(
                        source_schema=plan.schema_name or "dbo",
                        table_name=plan.table_name,
                        target_schema=plan.target_schema or "public",
                    )
                schema_map[catalog.source_schema.lower()] = catalog.target_schema
                table_result = await finalizer.finalize_table(
                    catalog,
                    options=opts,
                    schema_map=schema_map,
                    column_type_casts=casts or None,
                )
                for obj in table_result.objects:
                    state.set_object_status(
                        plan.table_name,
                        obj.object_type,
                        obj.object_key,
                        obj.status,
                    )
                    if obj.status == FinalizeObjectStatus.FAILED:
                        failures += 1

            if failures:
                state.status = FinalizePhaseStatus.PARTIAL
            else:
                state.status = FinalizePhaseStatus.COMPLETED
        except Exception as exc:
            state.status = FinalizePhaseStatus.FAILED
            state.last_error = str(exc)
            logger.error("post_migration_finalize_failed", job_id=str(job_id), error=str(exc))
        finally:
            await tgt_connector.disconnect()

        config = dict(job_rec.config or {})
        config["post_migration_finalize"] = state.to_dict()
        config["finalize_options"] = opts.to_dict()
        job_rec.config = config
        await session.commit()

    return state


async def get_finalize_status(job_id: UUID) -> dict[str, Any]:
    """Return post-migration finalize status and deferred object inventory."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from application.migration_service import (
        _derive_job_status,
        _go_job_data_complete,
        _reconcile_go_job_completion,
    )
    from domains.migration.migration_engine import MigrationJob, MigrationStatus, MigrationStrategy, TableMigrationPlan
    from infrastructure.metadata_db.models import MigrationJobRecord
    from infrastructure.metadata_db.session import AsyncSessionFactory

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(MigrationJobRecord)
            .where(MigrationJobRecord.migration_job_id == str(job_id))
            .options(selectinload(MigrationJobRecord.table_plans))
        )
        job_rec = result.scalar_one_or_none()
        if not job_rec:
            return {"job_id": str(job_id), "found": False}

        await _reconcile_go_job_completion(session, job_rec)

        config = job_rec.config or {}
        finalize_state = PostMigrationFinalizeState.from_dict(
            config.get("post_migration_finalize"),
        )
        options = PostMigrationFinalizeOptions.from_dict(config.get("finalize_options"))

        stub_job = MigrationJob(
            job_id=job_id,
            status=MigrationStatus((job_rec.status or "pending").lower()),
            tables=[
                TableMigrationPlan(
                    table_name=p.table_name,
                    schema_name=p.schema_name or "dbo",
                    target_schema=p.target_schema or "public",
                    columns=p.columns if p.columns else ["*"],
                    row_count_estimate=p.row_count_estimate or 0,
                    strategy=MigrationStrategy.CHUNKED,
                    status=p.status,
                    rows_migrated=p.rows_migrated or 0,
                )
                for p in job_rec.table_plans
            ],
        )
        effective_status = _derive_job_status(stub_job, job_rec)

        tables: list[dict[str, Any]] = []
        for plan in job_rec.table_plans:
            cfg = plan.plan_config or {}
            deferred = cfg.get("deferred_schema")
            inventory: dict[str, Any] = dict(_EMPTY_INVENTORY)
            if deferred:
                catalog = catalog_from_dict(deferred)
                inventory = {
                    "identities": [ic.column_name for ic in catalog.identity_columns],
                    "indexes": [
                        {
                            "name": ix.index_name,
                            "unsupported": ix.unsupported_reason,
                        }
                        for ix in catalog.secondary_indexes
                    ],
                    "foreign_keys": [fk.constraint_name for fk in catalog.foreign_keys],
                    "check_constraints": [c.constraint_name for c in catalog.check_constraints],
                    "defaults": [d.column_name for d in catalog.column_defaults],
                    "triggers": [t.trigger_name for t in catalog.triggers],
                }
            table_state = finalize_state.tables.get(plan.table_name, {})
            tables.append(
                {
                    "table_name": plan.table_name,
                    "source_schema": plan.schema_name,
                    "target_schema": plan.target_schema,
                    "inventory": inventory,
                    "applied": table_state,
                }
            )

        return {
            "job_id": str(job_id),
            "found": True,
            "migration_status": effective_status.value,
            "data_complete": _go_job_data_complete(job_rec),
            "finalize_status": finalize_state.status.value,
            "last_error": finalize_state.last_error,
            "options": options.to_dict(),
            "tables": tables,
        }
