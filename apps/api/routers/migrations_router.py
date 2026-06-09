# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""Migration job routes — CRUD + lifecycle control + progress."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

import application.migration_service as svc
from apps.api.middleware.auth import UserRole, require_role
from domains.licensing.editions import require_feature
from domains.licensing.license_enforcement import require_valid_license
from domains.migration.migration_engine import MigrationStatus, MigrationStrategy
from shared.errors.error_catalog import format_connection_error, format_error_response
from shared.tenancy.project_scope import resolve_project_filter

router = APIRouter(tags=["migrations"])


# ---- Models ----

class MaskingPolicy(StrEnum):
    NONE = "none"
    AUTO = "auto"
    STRICT = "strict"


class MigrationRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_connection_id: UUID
    target_connection_id: UUID
    tables: list[str]
    schema_name: str = Field(default="dbo", alias="schema")
    target_schema: str | None = None
    strategy: MigrationStrategy = MigrationStrategy.CHUNKED
    chunk_size: int = 10000
    parallel_workers: int = 4
    validate_after: bool = True
    masking_policy: MaskingPolicy = MaskingPolicy.NONE
    column_transforms: dict[str, str] = Field(default_factory=dict)
    column_sensitivity: dict[str, str] = Field(default_factory=dict)
    require_target_snapshot: bool = True
    snapshot_ref: str | None = None
    idempotent: bool = False
    table_policies: dict[str, str] = Field(default_factory=dict)
    finalize_after: bool = True
    finalize_identities: bool = True
    finalize_indexes: bool = True
    finalize_foreign_keys: bool = True
    finalize_check_constraints: bool = True
    finalize_defaults: bool = True
    finalize_triggers: bool = False
    create_indexes_concurrently: bool = False
    column_type_overrides: dict[str, str] = Field(default_factory=dict)
    procedures: list[str] = Field(default_factory=list)
    functions: list[str] = Field(default_factory=list)
    migrate_procedural_after_tables: bool = True


class ProceduralPreviewObject(BaseModel):
    name: str
    object_type: str = "procedure"


class ProceduralPreviewRequest(BaseModel):
    source_connection_id: UUID
    schema_name: str = Field(default="dbo", alias="schema")
    target_schema: str | None = None
    objects: list[ProceduralPreviewObject] = Field(default_factory=list)


class ProceduralPreviewItem(BaseModel):
    name: str
    object_type: str
    schema_name: str
    target_schema: str
    success: bool
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    converted_sql: str = ""
    manual_review_required: bool = False
    postgres_syntax_valid: bool = True
    target_validated: bool = False


class ProceduralMigrationStatusResponse(BaseModel):
    status: str
    source_schema: str = "dbo"
    target_schema: str = "public"
    selected_procedures: list[str] = Field(default_factory=list)
    selected_functions: list[str] = Field(default_factory=list)
    auto_migrate_after_tables: bool = True
    last_error: str | None = None
    objects: dict[str, dict] = Field(default_factory=dict)
    has_selection: bool = False


class MigrationPreflightRequest(BaseModel):
    source_connection_id: UUID
    target_connection_id: UUID
    tables: list[str]
    schema_name: str = Field(default="dbo", alias="schema")
    target_schema: str | None = None


class TargetTablePreflightEntry(BaseModel):
    table_name: str
    exists: bool
    row_count: int
    requires_action: bool
    suggested_policy: str | None
    message: str
    found_in_schema: str | None = None
    schema_mismatch: bool = False


class PausedMigrationMatch(BaseModel):
    job_id: str
    status: str
    overlapping_tables: list[dict]
    rows_migrated: int
    message: str


class MigrationPreflightResponse(BaseModel):
    tables: list[TargetTablePreflightEntry]
    paused_jobs: list[PausedMigrationMatch]
    has_conflicts: bool
    can_start_without_prompt: bool


class MigrationResponse(BaseModel):
    job_id: UUID
    status: MigrationStatus
    created_at: datetime
    table_count: int
    message: str = ""


class ProgressResponse(BaseModel):
    job_id: UUID
    status: MigrationStatus
    overall_percentage: float
    tables_progress: dict[str, dict]
    elapsed_seconds: float
    estimated_remaining_seconds: float
    throughput_rows_per_sec: float
    total_rows_migrated: int
    total_rows_estimate: int


# ---- Endpoints ----

@router.get("/migrations/column-type-override-options")
async def column_type_override_options(_: dict = require_role(UserRole.VIEWER)):
    """Return user-selectable PostgreSQL types for unsupported SQL Server columns."""
    from domains.migration.column_type_override import catalog_for_api

    return {"source_types": catalog_for_api()}


@router.post("/migrations/preflight", response_model=MigrationPreflightResponse)
async def migration_preflight(
    req: MigrationPreflightRequest,
    _: dict = require_role(UserRole.VIEWER),
):
    """Inspect target tables and detect paused jobs before starting a migration."""
    from application.go_engine_migration.target_table_preflight import (
        find_paused_migration_jobs,
        inspect_target_tables,
    )
    from apps.api.connection_store import get_entry
    from domains.migration.target_schema_resolver import resolve_target_schema

    if not req.tables:
        resolved_target_schema = resolve_target_schema(req.schema_name, req.target_schema)
        paused = await find_paused_migration_jobs(
            req.source_connection_id,
            req.target_connection_id,
            table_names=[],
            target_schema=resolved_target_schema,
        )
        return MigrationPreflightResponse(
            tables=[],
            paused_jobs=[PausedMigrationMatch(**p) for p in paused],
            has_conflicts=bool(paused),
            can_start_without_prompt=not paused,
        )

    resolved_target_schema = resolve_target_schema(req.schema_name, req.target_schema)

    tgt_entry = get_entry(str(req.target_connection_id))
    if not tgt_entry:
        raise HTTPException(status_code=404, detail="Target connection not found")

    try:
        tgt_connector, _ = await svc.make_connector(tgt_entry)
        await tgt_connector.connect()
        try:
            table_rows = await inspect_target_tables(
                tgt_connector,
                target_schema=resolved_target_schema,
                table_names=req.tables,
                source_schema=req.schema_name,
            )
        finally:
            await tgt_connector.disconnect()
    except (OSError, ConnectionError) as exc:
        raise HTTPException(
            status_code=502,
            detail=format_connection_error(str(exc), conn_type="target"),
        ) from exc
    except Exception as exc:
        if re.search(r"(?i)asyncpg|postgres|5432|pg_hba", str(exc)):
            raise HTTPException(
                status_code=502,
                detail=format_connection_error(str(exc), conn_type="target"),
            ) from exc
        raise

    paused = await find_paused_migration_jobs(
        req.source_connection_id,
        req.target_connection_id,
        table_names=req.tables,
        target_schema=resolved_target_schema,
    )

    has_conflicts = any(t["requires_action"] for t in table_rows) or bool(paused)
    can_start = not has_conflicts

    return MigrationPreflightResponse(
        tables=[TargetTablePreflightEntry(**t) for t in table_rows],
        paused_jobs=[PausedMigrationMatch(**p) for p in paused],
        has_conflicts=has_conflicts,
        can_start_without_prompt=can_start,
    )


@router.get("/migrations")
async def list_migrations(
    project_id: str | None = Query(default=None),
    user: dict = require_role(UserRole.VIEWER),
):
    await svc.refresh_all_jobs_from_metadata()
    scope = resolve_project_filter(
        project_id,
        user_project_id=user.get("project_id"),
        is_admin=user.get("role") == UserRole.ADMIN.value,
    )
    rows = []
    for jid, job in svc.list_jobs(project_id=scope):
        effective = svc._derive_job_status(job)
        rows.append({
            "job_id": str(jid),
            "status": effective.value if hasattr(effective, "value") else str(effective),
            "created_at": job.created_at.isoformat() if hasattr(job, "created_at") else "",
            "updated_at": job.updated_at.isoformat() if hasattr(job, "updated_at") else "",
            "table_count": len(job.tables),
            "project_id": getattr(job, "project_id", None),
        })
    return rows


@router.post("/migrations", response_model=MigrationResponse)
async def start_migration(req: MigrationRequest, _: dict = require_role(UserRole.OPERATOR)):
    require_valid_license()
    require_feature("migration")
    from application.migration_readiness_service import (
        MigrationReadinessError,
        validate_migration_routines_ready,
        validate_migration_tables_ready,
    )
    from application.migration_settings_config import get_max_tables_per_job
    from apps.api.connection_store import get_decrypted_password, get_entry

    max_tables = get_max_tables_per_job()
    if len(req.tables) > max_tables:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot migrate more than {max_tables} tables in one job "
                f"({len(req.tables)} selected). Adjust the limit in Settings → Migration."
            ),
        )

    has_routines = bool(req.procedures or req.functions)
    if not req.tables and not has_routines:
        raise HTTPException(
            status_code=400,
            detail="Select at least one table or stored procedure/function to migrate.",
        )

    src_entry = get_entry(str(req.source_connection_id))
    if not src_entry:
        raise HTTPException(status_code=404, detail="Source connection not found")
    tgt_entry = get_entry(str(req.target_connection_id))
    if not tgt_entry:
        raise HTTPException(status_code=404, detail="Target connection not found")
    database = src_entry.get("database", "")
    if not database:
        raise HTTPException(status_code=400, detail="Source connection has no database configured")
    from application.go_engine_migration.target_table_preflight import TargetTablePreflightError

    try:
        if req.tables:
            await validate_migration_tables_ready(
                req.source_connection_id,
                database=database,
                schema=req.schema_name,
                table_names=req.tables,
                entry=src_entry,
                password=get_decrypted_password(src_entry),
                column_type_overrides=req.column_type_overrides or None,
            )
        if has_routines:
            await validate_migration_routines_ready(
                database=database,
                schema=req.schema_name,
                procedure_names=req.procedures or [],
                function_names=req.functions or [],
                entry=src_entry,
                password=get_decrypted_password(src_entry),
                target_entry=tgt_entry,
                target_password=get_decrypted_password(tgt_entry),
                target_schema=req.target_schema,
                selected_tables=req.tables or None,
            )
        job = await svc.start_migration(
            source_connection_id=req.source_connection_id,
            target_connection_id=req.target_connection_id,
            tables=req.tables,
            schema=req.schema_name,
            strategy=req.strategy,
            chunk_size=req.chunk_size,
            parallel_workers=req.parallel_workers,
            target_schema=req.target_schema,
            masking_policy=req.masking_policy.value,
            column_transforms=req.column_transforms or None,
            column_sensitivity=req.column_sensitivity or None,
            require_target_snapshot=req.require_target_snapshot,
            snapshot_ref=req.snapshot_ref,
            idempotent=req.idempotent,
            validate_after=req.validate_after,
            table_policies=req.table_policies or None,
            finalize_after=req.finalize_after,
            finalize_options={
                "auto_finalize_after_validation": req.finalize_after,
                "finalize_identities": req.finalize_identities,
                "finalize_indexes": req.finalize_indexes,
                "finalize_foreign_keys": req.finalize_foreign_keys,
                "finalize_check_constraints": req.finalize_check_constraints,
                "finalize_defaults": req.finalize_defaults,
                "finalize_triggers": req.finalize_triggers,
                "create_indexes_concurrently": req.create_indexes_concurrently,
            },
            column_type_overrides=req.column_type_overrides or None,
            procedures=req.procedures or None,
            functions=req.functions or None,
            migrate_procedural_after_tables=req.migrate_procedural_after_tables,
        )
    except MigrationReadinessError as exc:
        raise HTTPException(status_code=400, detail=format_error_response(str(exc))) from exc
    except TargetTablePreflightError as exc:
        raise HTTPException(status_code=409, detail=format_error_response(str(exc))) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=format_error_response(str(exc))) from exc
    except (OSError, ConnectionError) as exc:
        raise HTTPException(
            status_code=502,
            detail=format_connection_error(str(exc), conn_type="target"),
        ) from exc
    except Exception as exc:
        msg = str(exc)
        if re.search(
            r"(?i)foreign key|integrityerror|migration_job_logs|migration_jobs|sqlalchemy\.dialects\.postgresql",
            msg,
        ):
            raise HTTPException(
                status_code=500,
                detail=format_error_response(
                    "Migration job could not be recorded in the platform database. Retry or check API logs."
                ),
            ) from exc
        conn_type = "source"
        if re.search(r"(?i)asyncpg|postgres|5432|pg_hba", msg):
            conn_type = "target"
        elif re.search(r"(?i)pyodbc|sql server|1433|odbc", msg):
            conn_type = "source"
        elif "asyncpg" in type(exc).__module__:
            conn_type = "target"
        raise HTTPException(
            status_code=502,
            detail=format_connection_error(msg, conn_type=conn_type),
        ) from exc
    routine_count = len(req.procedures or []) + len(req.functions or [])
    if req.tables:
        message = (
            f"Migration queued for Go engine — {len(req.tables)} table(s), "
            f"strategy={req.strategy.value}"
        )
        if routine_count:
            message += f" + {routine_count} routine(s) after tables"
    else:
        message = f"Procedural migration started — {routine_count} routine(s)"
    return MigrationResponse(
        job_id=job.job_id,
        status=job.status,
        created_at=job.created_at,
        table_count=len(req.tables),
        message=message,
    )


@router.get("/migrations/{job_id}")
async def get_migration(job_id: UUID):
    job = await svc.refresh_job_from_metadata(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    source_schema = job.tables[0].schema_name if job.tables else None
    target_schema = job.tables[0].target_schema if job.tables else None
    effective = svc._derive_job_status(job)
    status = effective.value if hasattr(effective, "value") else str(effective)
    procedural_payload = await _procedural_migration_payload(job)
    return {
        "job_id": job.job_id,
        "status": status,
        "executor": getattr(job, "executor", "go"),
        "tables": [
            {
                "table": t.table_name,
                "strategy": t.strategy.value,
                "schema": t.schema_name,
                "target_schema": t.target_schema,
                "status": t.status,
                "rows_migrated": t.rows_migrated,
                "row_count_estimate": t.row_count_estimate,
            }
            for t in job.tables
        ],
        "error_message": getattr(job, "error_message", None),
        "source_schema": source_schema,
        "target_schema": target_schema,
        "source_connection_id": str(job.source_connection_id),
        "target_connection_id": str(job.target_connection_id),
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "table_count": len(job.tables),
        "procedural_migration": procedural_payload,
    }


async def _procedural_migration_payload(job: object) -> dict | None:
    from application.procedural_migration_service import get_procedural_migration_status
    from domains.migration.procedural_migration_models import ProceduralMigrationState

    proc = getattr(job, "procedural_migration", None)
    if proc:
        state = ProceduralMigrationState.from_dict(proc)
    else:
        try:
            state = await get_procedural_migration_status(getattr(job, "job_id"))
        except Exception:
            return None
    if not state.has_selection() and state.status.value == "pending":
        return None
    payload = state.to_dict()
    payload["has_selection"] = state.has_selection()
    return payload


@router.post("/migrations/procedural/preview")
async def preview_procedural_migration(
    req: ProceduralPreviewRequest,
    _: dict = require_role(UserRole.OPERATOR),
):
    """Convert selected procedures/functions without applying to PostgreSQL."""
    from application.procedural_migration_service import preview_procedural_objects
    from apps.api.connection_store import get_entry
    from domains.migration.procedural_migration_models import ProceduralObjectSelection

    if not req.objects:
        raise HTTPException(status_code=400, detail="At least one object is required")

    entry = get_entry(str(req.source_connection_id))
    if not entry:
        raise HTTPException(status_code=404, detail="Source connection not found")

    selections = [
        ProceduralObjectSelection.from_name(obj.name, obj.object_type)
        for obj in req.objects
    ]
    try:
        previews = await preview_procedural_objects(
            source_entry=entry,
            source_schema=req.schema_name,
            target_schema=req.target_schema,
            objects=selections,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (OSError, ConnectionError) as exc:
        raise HTTPException(
            status_code=502,
            detail=format_connection_error(str(exc), conn_type="source"),
        ) from exc
    return {"items": [ProceduralPreviewItem(**item) for item in previews]}


@router.get("/migrations/{job_id}/procedural", response_model=ProceduralMigrationStatusResponse)
async def get_procedural_migration(job_id: UUID, _: dict = require_role(UserRole.VIEWER)):
    from application.procedural_migration_service import get_procedural_migration_status

    try:
        state = await get_procedural_migration_status(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    payload = state.to_dict()
    payload["has_selection"] = state.has_selection()
    return ProceduralMigrationStatusResponse(**payload)


@router.post("/migrations/{job_id}/procedural/migrate", response_model=ProceduralMigrationStatusResponse)
async def run_procedural_migration(
    job_id: UUID,
    _: dict = require_role(UserRole.OPERATOR),
):
    from application.procedural_migration_service import migrate_procedural_objects_for_job

    try:
        state = await migrate_procedural_objects_for_job(job_id, force=True)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (OSError, ConnectionError) as exc:
        raise HTTPException(
            status_code=502,
            detail=format_connection_error(str(exc), conn_type="target"),
        ) from exc
    payload = state.to_dict()
    payload["has_selection"] = state.has_selection()
    return ProceduralMigrationStatusResponse(**payload)


@router.get("/migrations/{job_id}/logs")
async def get_migration_logs(job_id: UUID):
    from application.go_engine_migration.migration_job_log_reader import (
        load_durable_migration_job_logs,
    )

    job = svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    logs = await load_durable_migration_job_logs(str(job_id))
    return {"job_id": str(job_id), "logs": logs}


@router.post("/migrations/{job_id}/pause")
async def pause_migration(job_id: UUID, _: dict = require_role(UserRole.OPERATOR)):
    try:
        job = await svc.pause_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"job_id": job_id, "status": job.status}


@router.post("/migrations/{job_id}/resume")
async def resume_migration(job_id: UUID, _: dict = require_role(UserRole.OPERATOR)):
    try:
        job = await svc.resume_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"job_id": job_id, "status": job.status}


@router.post("/migrations/{job_id}/stop")
async def stop_migration(job_id: UUID, _: dict = require_role(UserRole.OPERATOR)):
    try:
        job = await svc.stop_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job_id, "status": job.status}


@router.get("/migrations/{job_id}/progress", response_model=ProgressResponse)
async def get_migration_progress(job_id: UUID):
    job = await svc.refresh_job_from_metadata(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    snapshot = svc.build_progress_snapshot(job)
    return ProgressResponse(job_id=job_id, **snapshot)


@router.post("/migrations/{job_id}/provision-tables")
async def provision_migration_tables(job_id: UUID, _: dict = require_role(UserRole.OPERATOR)):
    """Create missing PostgreSQL target tables for an existing job (recovery helper)."""
    from application.go_engine_migration.provision_job_tables import provision_tables_for_job_id

    try:
        created = await provision_tables_for_job_id(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "job_id": str(job_id),
        "created_tables": created,
        "message": (
            f"Provisioned {len(created)} table(s)"
            if created
            else "All target tables already exist — nothing created"
        ),
    }


@router.get("/migrations/{job_id}/tables/{table_name}/progress")
async def get_table_progress(job_id: UUID, table_name: str):
    job = svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job = await svc.refresh_job_from_metadata(job_id) or job
    snapshot = svc.build_progress_snapshot(job)
    entry = snapshot["tables_progress"].get(table_name)
    if not entry:
        raise HTTPException(status_code=404, detail="Table progress not found")
    return {
        "table_name": entry["table_name"],
        "schema_name": entry["schema_name"],
        "total_rows_estimate": entry["total_rows_estimate"],
        "rows_migrated": entry["rows_migrated"],
        "percentage": entry["percentage"],
        "current_chunk": entry["current_chunk"],
        "total_chunks": entry["total_chunks"],
        "status": entry["status"],
        "throughput_rows_per_sec": entry["throughput_rows_per_sec"],
        "elapsed_seconds": entry["elapsed_seconds"],
        "estimated_remaining_seconds": entry["estimated_remaining_seconds"],
    }


class PostMigrationFinalizeRequest(BaseModel):
    finalize_identities: bool = True
    finalize_indexes: bool = True
    finalize_foreign_keys: bool = True
    finalize_check_constraints: bool = True
    finalize_defaults: bool = True
    finalize_triggers: bool = False
    create_indexes_concurrently: bool = False


@router.get("/migrations/{job_id}/post-migration")
async def get_post_migration_status(job_id: UUID, _: dict = require_role(UserRole.VIEWER)):
    """Return deferred schema inventory and post-migration finalize progress."""
    from application.go_engine_migration.post_migration_finalizer import get_finalize_status

    status = await get_finalize_status(job_id)
    if not status.get("found"):
        raise HTTPException(status_code=404, detail="Job not found")
    return status


@router.post("/migrations/{job_id}/post-migration/finalize")
async def run_post_migration_finalize(
    job_id: UUID,
    req: PostMigrationFinalizeRequest,
    _: dict = require_role(UserRole.OPERATOR),
):
    """Apply deferred post-migration schema objects (identity, indexes, constraints)."""
    from application.go_engine_migration.post_migration_finalizer import finalize_migration_job
    from domains.migration.post_migration_finalize_models import PostMigrationFinalizeOptions

    job = await svc.refresh_job_from_metadata(job_id) or svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    effective = svc._derive_job_status(job)
    if effective != MigrationStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail="Post-migration finalize requires a completed migration job",
        )

    options = PostMigrationFinalizeOptions(
        auto_finalize_after_validation=True,
        finalize_identities=req.finalize_identities,
        finalize_indexes=req.finalize_indexes,
        finalize_foreign_keys=req.finalize_foreign_keys,
        finalize_check_constraints=req.finalize_check_constraints,
        finalize_defaults=req.finalize_defaults,
        finalize_triggers=req.finalize_triggers,
        create_indexes_concurrently=req.create_indexes_concurrently,
    )
    state = await finalize_migration_job(job_id, options=options)
    return {
        "job_id": str(job_id),
        "status": state.status.value,
        "last_error": state.last_error,
        "tables": state.tables,
    }
