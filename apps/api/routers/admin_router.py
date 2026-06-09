"""
Module: apps/api/routers/admin_router.py
Purpose: Admin-only management endpoints — job retention, platform diagnostics,
         and ODBC driver availability check.  Restricted to ADMIN role.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from application.audit_service import AuditService
from application.migration_settings_config import migration_settings_status
from application.replication_settings_config import replication_settings_status
from application.replication_runtime import get_runtime_manager
from apps.api.middleware.auth import UserRole, require_role
from apps.api.migration_settings_store import (
    save_settings_async as save_migration_settings_async,
    set_settings as set_migration_settings,
)
from apps.api.replication_settings_store import (
    save_settings_async as save_replication_settings_async,
    set_settings as set_replication_settings,
)
from shared.security.audit_log import AuditAction
from shared.tenancy.project_scope import resolve_project_filter
from infrastructure.metadata_db.session import AsyncSessionFactory
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class RetentionRequest(BaseModel):
    max_age_days: int = Field(default=90, ge=1, le=3650)
    keep_failed: bool = False
    dry_run: bool = False


class RetentionResponse(BaseModel):
    policy_max_age_days: int
    scanned: int
    deleted: int
    skipped: int
    dry_run: bool
    ran_at: str


class OdbcCheckResponse(BaseModel):
    available: bool
    drivers: list[str]
    message: str


class MigrationSettingsUpdate(BaseModel):
    source_throttle_enabled: bool = True
    small_table_delay_sec: float = Field(default=1.0, ge=0.0, le=300.0)
    large_table_delay_sec: float = Field(default=4.0, ge=0.0, le=600.0)
    large_table_row_threshold: int = Field(default=100_000, ge=1, le=1_000_000_000)
    large_table_size_mb_threshold: float = Field(default=50.0, ge=0.1, le=1_000_000.0)
    max_tables_per_job: int = Field(default=25, ge=1, le=500)


class ReplicationSettingsUpdate(BaseModel):
    poll_interval_ms: int = Field(default=1000, ge=100, le=600_000)
    batch_size: int = Field(default=1000, ge=1, le=10_000)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/retention/run", response_model=RetentionResponse)
async def run_retention(
    req: RetentionRequest,
    _: dict = require_role(UserRole.ADMIN),
) -> RetentionResponse:
    """Trigger a job-retention sweep.  Set ``dry_run=true`` to preview deletions."""
    from application.retention_service import RetentionService
    from domains.migration.retention_policy import RetentionPolicy

    policy = RetentionPolicy(
        max_age_days=req.max_age_days,
        keep_failed=req.keep_failed,
    )
    async with AsyncSessionFactory() as session:
        svc = RetentionService(session, policy)
        result = await svc.run(dry_run=req.dry_run)
        if not req.dry_run:
            await session.commit()

    logger.info(
        "retention_sweep_complete",
        scanned=result.scanned,
        deleted=result.deleted,
        dry_run=req.dry_run,
    )
    return RetentionResponse(
        policy_max_age_days=result.policy_max_age_days,
        scanned=result.scanned,
        deleted=result.deleted,
        skipped=result.skipped,
        dry_run=req.dry_run,
        ran_at=result.ran_at,
    )


@router.get("/odbc/check", response_model=OdbcCheckResponse)
async def check_odbc(
    _: dict = require_role(UserRole.ADMIN),
) -> OdbcCheckResponse:
    """Return available ODBC drivers installed on the host."""
    try:
        import pyodbc

        drivers: list[str] = list(pyodbc.drivers())
        has_sqlserver = any(
            "SQL Server" in d or "ODBC Driver" in d for d in drivers
        )
        return OdbcCheckResponse(
            available=has_sqlserver,
            drivers=drivers,
            message=(
                "SQL Server ODBC driver found"
                if has_sqlserver
                else "No SQL Server ODBC driver detected — install 'ODBC Driver 18 for SQL Server'"
            ),
        )
    except ImportError:
        return OdbcCheckResponse(
            available=False,
            drivers=[],
            message="pyodbc not installed",
        )


class AuditLogEntryResponse(BaseModel):
    id: str
    timestamp: str
    action: str
    actor: str
    resource: str
    details: dict | None = None
    correlation_id: str | None = None
    source_ip: str | None = None
    success: bool
    error_message: str | None = None


@router.get("/audit-log", response_model=list[AuditLogEntryResponse])
async def query_audit_log(
    action: str | None = Query(default=None),
    actor: str | None = Query(default=None),
    resource: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    user: dict = require_role(UserRole.ADMIN),
) -> list[AuditLogEntryResponse]:
    """Read-only, filterable audit trail for compliance review."""
    audit_action = None
    if action:
        try:
            audit_action = AuditAction(action)
        except ValueError:
            pass
    scope = resolve_project_filter(
        project_id,
        user_project_id=user.get("project_id"),
        is_admin=user.get("role") == UserRole.ADMIN.value,
    )
    async with AsyncSessionFactory() as session:
        entries = await AuditService(session).query(
            action=audit_action,
            actor=actor,
            resource=resource,
            project_id=scope,
            limit=limit,
            offset=offset,
        )
    return [
        AuditLogEntryResponse(
            id=e.audit_log_id,
            timestamp=e.timestamp.isoformat(),
            action=e.action,
            actor=e.actor,
            resource=e.resource,
            details=e.details,
            correlation_id=e.correlation_id,
            source_ip=e.source_ip,
            success=e.success,
            error_message=e.error_message,
        )
        for e in entries
    ]


@router.get("/diagnostics")
async def diagnostics(
    _: dict = require_role(UserRole.ADMIN),
) -> dict:
    """Return basic platform diagnostics (DB connectivity, env var presence)."""
    import os

    from infrastructure.metadata_db.session import AsyncSessionFactory

    env_checks = {
        "MIGRATION_JWT_SECRET": bool(os.environ.get("MIGRATION_JWT_SECRET")),
        "MIGRATION_MASTER_KEY": bool(os.environ.get("MIGRATION_MASTER_KEY")),
        "MIGRATION_ADMIN_PASSWORD": bool(os.environ.get("MIGRATION_ADMIN_PASSWORD")),
        "METADATA_DB_URL": bool(os.environ.get("METADATA_DB_URL")),
    }

    db_ok = False
    db_error: str | None = None
    try:
        async with AsyncSessionFactory() as sess:
            await sess.execute(__import__("sqlalchemy").text("SELECT 1"))
        db_ok = True
    except Exception as exc:
        db_error = str(exc)

    return {
        "env_vars": env_checks,
        "metadata_db": {"connected": db_ok, "error": db_error},
    }


@router.get("/metadata-security")
async def get_metadata_security(_: dict = require_role(UserRole.ADMIN)) -> dict:
    """Audit metadata DB credential storage (§12.8)."""
    from application.metadata_security_service import MetadataSecurityService

    async with AsyncSessionFactory() as session:
        report = await MetadataSecurityService().audit(session)
    return report.to_dict()


@router.get("/edition")
async def get_product_edition(_: dict = require_role(UserRole.VIEWER)) -> dict:
    """Current product edition and enabled features (§13.8)."""
    from domains.licensing.editions import edition_info

    return edition_info()


@router.get("/usage")
async def get_usage_metering(
    days: int = Query(default=30, ge=1, le=365),
    _: dict = require_role(UserRole.ADMIN),
) -> dict:
    """Usage metering summary from audit + job metadata (§13.8)."""
    from domains.observability.metering import UsageMeteringService

    async with AsyncSessionFactory() as session:
        return await UsageMeteringService().summary(session, days=days)


@router.get("/slos")
async def get_platform_slos(_: dict = require_role(UserRole.VIEWER)) -> dict:
    """Published SLO targets and capacity guidance (§13.12)."""
    from domains.observability.slos import MIGRATION_SLOS, capacity_table

    return {
        "slos": [
            {"name": s.name, "target": s.target, "measurement": s.measurement, "notes": s.notes}
            for s in MIGRATION_SLOS
        ],
        "capacity": capacity_table(),
    }


@router.get("/go-engine/health")
async def go_engine_health(
    within_seconds: int = Query(default=60, ge=5, le=600),
    _: dict = require_role(UserRole.ADMIN),
) -> dict:
    """Report Go migration-engine worker heartbeats from the metadata DB."""
    from application.go_engine_migration.go_worker_health_checker import GoWorkerHealthChecker

    return await GoWorkerHealthChecker().worker_status(within_seconds=within_seconds)


@router.get("/migration-settings")
async def get_migration_settings_config(_: dict = require_role(UserRole.VIEWER)) -> dict:
    """Platform migration throttle and per-job table limits (readable by all roles)."""
    return migration_settings_status()


@router.put("/migration-settings")
async def update_migration_settings_config(
    req: MigrationSettingsUpdate,
    _: dict = require_role(UserRole.ADMIN),
) -> dict:
    """Update platform migration settings (admin only)."""
    if req.small_table_delay_sec > req.large_table_delay_sec:
        raise HTTPException(
            status_code=400,
            detail="Small-table delay must not exceed large-table delay",
        )
    set_migration_settings(
        {
            "source_throttle_enabled": req.source_throttle_enabled,
            "small_table_delay_sec": req.small_table_delay_sec,
            "large_table_delay_sec": req.large_table_delay_sec,
            "large_table_row_threshold": req.large_table_row_threshold,
            "large_table_size_mb_threshold": req.large_table_size_mb_threshold,
            "max_tables_per_job": req.max_tables_per_job,
        }
    )
    await save_migration_settings_async()
    return migration_settings_status()


@router.get("/replication-settings")
async def get_replication_settings_config(_: dict = require_role(UserRole.VIEWER)) -> dict:
    """Platform CDC poll interval and batch size (readable by all roles)."""
    return replication_settings_status()


@router.put("/replication-settings")
async def update_replication_settings_config(
    req: ReplicationSettingsUpdate,
    _: dict = require_role(UserRole.ADMIN),
) -> dict:
    """Update platform replication capture settings and apply to active streams."""
    set_replication_settings(
        {
            "poll_interval_ms": req.poll_interval_ms,
            "batch_size": req.batch_size,
        }
    )
    await save_replication_settings_async()
    active_streams_updated = get_runtime_manager().apply_capture_settings(
        req.poll_interval_ms,
        req.batch_size,
    )
    status = replication_settings_status()
    status["active_streams_updated"] = active_streams_updated
    return status
