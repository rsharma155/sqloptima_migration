"""
Module: procedural_migration_service.py
Purpose: Convert and apply SQL Server stored procedures / functions to PostgreSQL.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from uuid import UUID

from application.conversion_factory import build_conversion_service, build_schema_mapping
from application.conversion_service import ConversionRequest
from domains.migration.procedural_migration_models import (
    ProceduralMigrationPhaseStatus,
    ProceduralMigrationState,
    ProceduralMigrateStatus,
    ProceduralObjectKind,
    ProceduralObjectResult,
    ProceduralObjectSelection,
)
from domains.migration.target_schema_resolver import resolve_target_schema
from domains.validation.postgres_routine_deploy_validator import deploy_and_verify_routine
from shared.kernel.ddl_identifier import quote_pg_ident, validate_sql_identifier
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

_SCHEMA_QUALIFIER_RE = re.compile(
    r"\b(?P<schema>[A-Za-z_][A-Za-z0-9_]*)\.",
)


def _rewrite_routine_schema_qualifiers(
    sql: str,
    source_schema: str,
    target_schema: str,
) -> str:
    """Map source schema qualifiers in generated PL/pgSQL to the target schema."""
    resolved = resolve_target_schema(source_schema, target_schema)
    src = source_schema.strip()
    if not src or src.lower() == resolved.lower():
        return sql

    def _replace(match: re.Match[str]) -> str:
        found = match.group("schema")
        if found.lower() == src.lower():
            return f"{resolved}."
        return match.group(0)

    return _SCHEMA_QUALIFIER_RE.sub(_replace, sql)


def _summarize_procedural_failures(state: ProceduralMigrationState) -> str | None:
    """Build a human-readable summary when one or more routines fail."""
    failed: list[str] = []
    for key, obj in state.objects.items():
        if (obj.status.value if hasattr(obj.status, "value") else str(obj.status)) != "failed":
            continue
        detail = "; ".join(obj.errors) if obj.errors else "manual review required"
        if obj.warnings and not obj.errors:
            detail = obj.warnings[-1]
        failed.append(f"{key}: {detail}")
    if not failed:
        return None
    if len(failed) == 1:
        return failed[0]
    return f"{len(failed)} routine(s) failed — " + " | ".join(failed[:3])

# Re-export for tests and callers that imported from here.
__all__ = [
    "build_initial_procedural_state",
    "build_schema_mapping",
    "get_procedural_migration_status",
    "migrate_procedural_objects_for_job",
    "preview_procedural_objects",
]


async def _fetch_object_definition(
    connector: Any,
    *,
    schema_name: str,
    object_name: str,
) -> str | None:
    rows = await connector.execute(
        "SELECT OBJECT_DEFINITION(OBJECT_ID(N'[' + ? + '].[' + ? + ']')) AS definition",
        {"schema": schema_name, "name": object_name},
    )
    if not rows:
        return None
    return rows[0].get("definition")


async def _ensure_target_schema(connector: Any, target_schema: str) -> None:
    if target_schema.lower() == "public":
        return
    await connector.execute(
        f"CREATE SCHEMA IF NOT EXISTS {quote_pg_ident(target_schema)}"
    )


def _convert_definition(
    *,
    sql: str,
    object_type: ProceduralObjectKind,
    schema_name: str,
    object_name: str,
    target_schema: str | None,
) -> ProceduralObjectResult:
    """Convert using the same ConversionService pipeline as POST /api/v1/convert."""
    service = build_conversion_service(schema_name, target_schema)
    conversion_type = "procedure" if object_type == ProceduralObjectKind.PROCEDURE else "function"
    result = service.convert(
        ConversionRequest(
            sql=sql,
            object_type=conversion_type,
            schema=schema_name,
            name=object_name,
        )
    )
    obj = ProceduralObjectResult(
        name=object_name,
        schema_name=schema_name,
        object_type=object_type,
        success=result.success and bool(result.converted_sql),
        warnings=list(result.warnings),
        errors=list(result.errors),
        manual_review_required=result.manual_review_required,
        postgres_syntax_valid=result.postgres_syntax_valid,
        converted_sql=result.converted_sql or "",
    )
    if not sql.strip():
        obj.success = False
        obj.errors.append("Source definition is empty")
        obj.status = ProceduralMigrateStatus.FAILED
    elif not obj.converted_sql.strip():
        obj.success = False
        if not obj.errors:
            obj.errors.append("Conversion produced empty SQL")
        obj.status = ProceduralMigrateStatus.FAILED
    elif not result.postgres_syntax_valid:
        obj.success = False
        obj.manual_review_required = True
        obj.status = ProceduralMigrateStatus.FAILED
        if not any(e.startswith("PostgreSQL syntax:") for e in obj.errors):
            obj.errors.append("PostgreSQL syntax validation failed (pgparse)")
    else:
        obj.success = bool(result.success and obj.converted_sql.strip())
        obj.status = (
            ProceduralMigrateStatus.PENDING if obj.success else ProceduralMigrateStatus.FAILED
        )
    return obj


def _conversion_ready(obj: ProceduralObjectResult) -> bool:
    """True when converted SQL is valid enough to deploy on PostgreSQL."""
    return (
        obj.success
        and obj.postgres_syntax_valid
        and bool(obj.converted_sql.strip())
        and not obj.errors
    )


async def preview_procedural_objects(
    *,
    source_entry: dict,
    source_schema: str,
    target_schema: str | None,
    objects: list[ProceduralObjectSelection],
) -> list[dict[str, Any]]:
    """Convert selected objects without applying to the target database."""
    from application.migration_service import make_connector

    if not objects:
        return []

    resolved_target = resolve_target_schema(source_schema, target_schema)
    src_connector, _ = await make_connector(source_entry)
    await src_connector.connect()
    previews: list[dict[str, Any]] = []
    try:
        loop = asyncio.get_running_loop()
        for sel in objects:
            validate_sql_identifier(sel.name, "object_name")
            validate_sql_identifier(source_schema, "schema")
            definition = await _fetch_object_definition(
                src_connector,
                schema_name=source_schema,
                object_name=sel.name,
            )
            if not definition:
                previews.append(
                    {
                        "name": sel.name,
                        "object_type": sel.object_type.value,
                        "schema_name": source_schema,
                        "target_schema": resolved_target,
                        "success": False,
                        "errors": ["Could not read source definition"],
                        "warnings": [],
                        "converted_sql": "",
                        "manual_review_required": True,
                        "postgres_syntax_valid": False,
                        "target_validated": False,
                    }
                )
                continue
            converted = await loop.run_in_executor(
                None,
                lambda d=definition, s=sel: _convert_definition(
                    sql=d,
                    object_type=s.object_type,
                    schema_name=source_schema,
                    object_name=s.name,
                    target_schema=target_schema,
                ),
            )
            previews.append(
                {
                    "name": converted.name,
                    "object_type": converted.object_type.value,
                    "schema_name": converted.schema_name,
                    "target_schema": resolved_target,
                    "success": _conversion_ready(converted),
                    "warnings": converted.warnings,
                    "errors": converted.errors,
                    "converted_sql": converted.converted_sql,
                    "manual_review_required": converted.manual_review_required,
                    "postgres_syntax_valid": converted.postgres_syntax_valid,
                    "target_validated": False,
                }
            )
    finally:
        await src_connector.disconnect()
    return previews


async def migrate_procedural_objects_for_job(
    job_id: UUID,
    *,
    force: bool = False,
) -> ProceduralMigrationState:
    """Convert and apply selected procedures/functions for a migration job."""
    from sqlalchemy import select

    from application.migration_service import _append_job_log_durable, make_connector
    from apps.api.connection_store import get_entry
    from infrastructure.metadata_db.models import MigrationJobRecord
    from infrastructure.metadata_db.session import AsyncSessionFactory

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(MigrationJobRecord).where(
                MigrationJobRecord.migration_job_id == str(job_id)
            )
        )
        job_rec = result.scalar_one_or_none()
        if job_rec is None:
            raise ValueError(f"Migration job {job_id} not found")

        config = dict(job_rec.config or {})
        state = ProceduralMigrationState.from_dict(config.get("procedural_migration"))
        if not state.has_selection():
            state.status = ProceduralMigrationPhaseStatus.SKIPPED
            config["procedural_migration"] = state.to_dict()
            job_rec.config = config
            await session.commit()
            return state

        if (
            not force
            and state.status
            in {
                ProceduralMigrationPhaseStatus.COMPLETED,
                ProceduralMigrationPhaseStatus.IN_PROGRESS,
            }
        ):
            return state

        src_entry = get_entry(str(job_rec.source_project_connection_id))
        tgt_entry = get_entry(str(job_rec.target_project_connection_id))
        if not src_entry or not tgt_entry:
            raise ValueError("Source or target connection not found for job")

        state.status = ProceduralMigrationPhaseStatus.IN_PROGRESS
        state.last_error = None
        config["procedural_migration"] = state.to_dict()
        job_rec.config = config
        await session.commit()

    await _append_job_log_durable(
        job_id,
        f"Starting procedural migration — "
        f"{len(state.selected_procedures)} procedure(s), "
        f"{len(state.selected_functions)} function(s)",
        level="info",
    )

    src_connector, _ = await make_connector(src_entry)
    tgt_connector, _ = await make_connector(tgt_entry)
    await src_connector.connect()
    await tgt_connector.connect()
    loop = asyncio.get_running_loop()
    failures = 0

    try:
        await _ensure_target_schema(tgt_connector, state.target_schema)
        for sel in state.selected_objects():
            key = f"{state.source_schema}.{sel.name}"
            try:
                validate_sql_identifier(sel.name, "object_name")
                definition = await _fetch_object_definition(
                    src_connector,
                    schema_name=state.source_schema,
                    object_name=sel.name,
                )
                if not definition:
                    obj = ProceduralObjectResult(
                        name=sel.name,
                        schema_name=state.source_schema,
                        object_type=sel.object_type,
                        status=ProceduralMigrateStatus.FAILED,
                        success=False,
                        errors=["Could not read source definition"],
                        manual_review_required=True,
                    )
                    state.objects[key] = obj
                    failures += 1
                    continue

                converted = await loop.run_in_executor(
                    None,
                    lambda d=definition, s=sel: _convert_definition(
                        sql=d,
                        object_type=s.object_type,
                        schema_name=state.source_schema,
                        object_name=s.name,
                        target_schema=state.target_schema,
                    ),
                )

                if not _conversion_ready(converted):
                    converted.status = ProceduralMigrateStatus.FAILED
                    state.objects[key] = converted
                    failures += 1
                    detail = "; ".join(converted.errors) or "manual review required"
                    await _append_job_log_durable(
                        job_id,
                        f"Procedural conversion failed for {key}: {detail}",
                        level="warning",
                    )
                    continue

                deploy_sql = _rewrite_routine_schema_qualifiers(
                    converted.converted_sql,
                    state.source_schema,
                    state.target_schema,
                )
                converted.converted_sql = deploy_sql

                deploy = await deploy_and_verify_routine(
                    tgt_connector,
                    sql=deploy_sql,
                    target_schema=state.target_schema,
                    object_name=sel.name,
                    object_kind=sel.object_type,
                )
                if not deploy.target_validated:
                    converted.status = ProceduralMigrateStatus.FAILED
                    converted.success = False
                    converted.errors.extend(deploy.errors)
                    converted.manual_review_required = True
                    state.objects[key] = converted
                    failures += 1
                    await _append_job_log_durable(
                        job_id,
                        f"Target validation failed for {key}: "
                        f"{'; '.join(deploy.errors)}",
                        level="error",
                    )
                    continue

                converted.status = ProceduralMigrateStatus.APPLIED
                converted.success = True
                converted.target_validated = True
                converted.runtime_smoke_executed = deploy.runtime_smoke_executed
                converted.runtime_smoke_passed = deploy.runtime_smoke_passed
                converted.runtime_smoke_skipped = deploy.runtime_smoke_skipped
                converted.runtime_smoke_message = deploy.runtime_smoke_message
                if deploy.runtime_smoke_skipped and deploy.runtime_smoke_message:
                    converted.warnings.append(deploy.runtime_smoke_message)
                state.objects[key] = converted
                smoke_detail = (
                    "runtime smoke passed"
                    if deploy.runtime_smoke_passed
                    else deploy.runtime_smoke_message or "runtime smoke skipped"
                )
                await _append_job_log_durable(
                    job_id,
                    f"Applied and validated {sel.object_type.value} {key} on PostgreSQL ({smoke_detail})",
                    level="success",
                )
            except Exception as exc:
                failures += 1
                state.objects[key] = ProceduralObjectResult(
                    name=sel.name,
                    schema_name=state.source_schema,
                    object_type=sel.object_type,
                    status=ProceduralMigrateStatus.FAILED,
                    success=False,
                    errors=[str(exc)],
                    manual_review_required=True,
                )
                await _append_job_log_durable(
                    job_id,
                    f"Failed to migrate {key}: {exc}",
                    level="error",
                )
                logger.warning(
                    "procedural_migration_object_failed",
                    job_id=str(job_id),
                    object_key=key,
                    error=str(exc),
                )
    finally:
        await src_connector.disconnect()
        await tgt_connector.disconnect()

    if failures:
        state.status = (
            ProceduralMigrationPhaseStatus.FAILED
            if failures == len(state.selected_objects())
            else ProceduralMigrationPhaseStatus.PARTIAL
        )
        state.last_error = _summarize_procedural_failures(state) or f"{failures} object(s) failed"
    else:
        state.status = ProceduralMigrationPhaseStatus.COMPLETED
        state.last_error = None

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(MigrationJobRecord).where(
                MigrationJobRecord.migration_job_id == str(job_id)
            )
        )
        job_rec = result.scalar_one_or_none()
        if job_rec:
            config = dict(job_rec.config or {})
            config["procedural_migration"] = state.to_dict()
            job_rec.config = config
            await session.commit()

    summary = (
        "Procedural migration completed successfully"
        if state.status == ProceduralMigrationPhaseStatus.COMPLETED
        else f"Procedural migration finished with status {state.status.value}"
    )
    await _append_job_log_durable(job_id, summary, level="info" if failures == 0 else "warning")
    return state


async def get_procedural_migration_status(job_id: UUID) -> ProceduralMigrationState:
    from sqlalchemy import select

    from infrastructure.metadata_db.models import MigrationJobRecord
    from infrastructure.metadata_db.session import AsyncSessionFactory

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(MigrationJobRecord).where(
                MigrationJobRecord.migration_job_id == str(job_id)
            )
        )
        job_rec = result.scalar_one_or_none()
        if job_rec is None:
            raise ValueError(f"Migration job {job_id} not found")
        config = job_rec.config or {}
        return ProceduralMigrationState.from_dict(config.get("procedural_migration"))


def build_initial_procedural_state(
    *,
    source_schema: str,
    target_schema: str | None,
    procedures: list[str] | None,
    functions: list[str] | None,
    auto_migrate_after_tables: bool = True,
) -> ProceduralMigrationState | None:
    proc_list = [p.strip() for p in (procedures or []) if p and p.strip()]
    func_list = [f.strip() for f in (functions or []) if f and f.strip()]
    if not proc_list and not func_list:
        return None
    return ProceduralMigrationState(
        source_schema=source_schema,
        target_schema=resolve_target_schema(source_schema, target_schema),
        selected_procedures=proc_list,
        selected_functions=func_list,
        auto_migrate_after_tables=auto_migrate_after_tables,
        status=ProceduralMigrationPhaseStatus.PENDING,
    )
