# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""Migration job routes — CRUD + lifecycle control + progress."""

from __future__ import annotations

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
from shared.errors.error_catalog import format_error_response
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
    target_schema: str = "public"
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
    from application.migration_readiness_service import MigrationReadinessError, validate_migration_tables_ready
    from apps.api.connection_store import get_decrypted_password, get_entry

    src_entry = get_entry(str(req.source_connection_id))
    if not src_entry:
        raise HTTPException(status_code=404, detail="Source connection not found")
    database = src_entry.get("database", "")
    if not database:
        raise HTTPException(status_code=400, detail="Source connection has no database configured")
    try:
        await validate_migration_tables_ready(
            req.source_connection_id,
            database=database,
            schema=req.schema_name,
            table_names=req.tables,
            entry=src_entry,
            password=get_decrypted_password(src_entry),
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
        )
    except MigrationReadinessError as exc:
        raise HTTPException(status_code=400, detail=format_error_response(str(exc))) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=format_error_response(str(exc))) from exc
    return MigrationResponse(
        job_id=job.job_id,
        status=job.status,
        created_at=job.created_at,
        table_count=len(req.tables),
        message=f"Migration queued for Go engine — {len(req.tables)} table(s), strategy={req.strategy.value}",
    )


@router.get("/migrations/{job_id}")
async def get_migration(job_id: UUID):
    job = svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job = await svc.refresh_job_from_metadata(job_id) or job
    source_schema = job.tables[0].schema_name if job.tables else None
    target_schema = job.tables[0].target_schema if job.tables else None
    effective = svc._derive_job_status(job)
    status = effective.value if hasattr(effective, "value") else str(effective)
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
    }


@router.get("/migrations/{job_id}/logs")
async def get_migration_logs(job_id: UUID):
    from application.go_engine_migration.migration_job_log_reader import (
        load_durable_migration_job_logs,
    )

    job = svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    durable_logs = await load_durable_migration_job_logs(str(job_id))
    logs = durable_logs if durable_logs else getattr(job, "logs", [])
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
    job = svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job = await svc.refresh_job_from_metadata(job_id) or job
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
    p = job.progress.get(table_name)
    if not p:
        raise HTTPException(status_code=404, detail="Table progress not found")
    return {
        "table_name": p.table_name, "schema_name": p.schema_name,
        "total_rows_estimate": p.total_rows_estimate, "rows_migrated": p.rows_migrated,
        "percentage": p.percentage, "current_chunk": p.current_chunk,
        "total_chunks": p.total_chunks, "status": p.status,
        "throughput_rows_per_sec": p.throughput_rows_per_sec,
        "elapsed_seconds": p.elapsed_seconds,
        "estimated_remaining_seconds": p.estimated_remaining_seconds,
    }
