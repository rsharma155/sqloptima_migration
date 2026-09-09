"""
Module: apps/api/routers/reports_router.py
Purpose: Endpoints to retrieve persisted migration and validation reports in
         JSON and HTML formats.  All data is read from the metadata repository;
         no live source/target database connections are required.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

from application.reporting_service import ReportingService, ReportingServiceError
from apps.api.middleware.auth import UserRole, require_role
from domains.reporting.executive_report import ExecutiveReportBuilder
from infrastructure.metadata_db.session import AsyncSessionFactory
from shared.logging.structured_logging import get_logger
from shared.tenancy.project_scope import assert_resource_project_access

logger = get_logger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])


def _is_admin(user: dict) -> bool:
    return user.get("role") == UserRole.ADMIN.value


def _assert_report_job_access(summary: dict, user: dict) -> None:
    assert_resource_project_access(
        summary.get("project_id"),
        user_project_id=user.get("project_id"),
        is_admin=_is_admin(user),
    )


# ---------------------------------------------------------------------------
# Migration summary report
# ---------------------------------------------------------------------------


@router.get("/migration/{job_id}")
async def get_migration_report(
    job_id: UUID,
    fmt: str = Query(default="json", pattern="^(json|html)$"),
    user: dict = require_role(UserRole.VIEWER),
) -> Any:
    """Return a migration summary report for *job_id* in JSON or HTML."""
    async with AsyncSessionFactory() as session:
        svc = ReportingService(session)
        try:
            summary = await svc.migration_summary(str(job_id))
        except ReportingServiceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.error("migration_report_failed", job_id=str(job_id), error=str(exc))
            raise HTTPException(
                status_code=500, detail=f"Report generation failed: {exc}"
            ) from exc

    _assert_report_job_access(summary, user)

    if fmt == "html":
        return HTMLResponse(content=ReportingService.migration_summary_html(summary))
    return JSONResponse(content=summary)


# ---------------------------------------------------------------------------
# Validation summary report
# ---------------------------------------------------------------------------


@router.get("/validation/{job_id}")
async def get_validation_summary_report(
    job_id: UUID,
    user: dict = require_role(UserRole.VIEWER),
) -> Any:
    """Return an aggregated validation summary for all runs under *job_id*."""
    async with AsyncSessionFactory() as session:
        svc = ReportingService(session)
        try:
            summary = await svc.validation_summary(str(job_id))
        except ReportingServiceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.error(
                "validation_report_failed", job_id=str(job_id), error=str(exc)
            )
            raise HTTPException(
                status_code=500, detail=f"Report generation failed: {exc}"
            ) from exc

    _assert_report_job_access(summary, user)
    return JSONResponse(content=summary)


# ---------------------------------------------------------------------------
# Executive business summary (§13.6)
# ---------------------------------------------------------------------------


@router.get("/executive")
async def get_executive_report(
    project_name: str = "Migration Program",
    source_database: str = "SQL Server",
    total_objects: int = 0,
    auto_convertible: int = 0,
    partial: int = 0,
    unsupported: int = 0,
    risky: int = 0,
    blocker_count: int = 0,
    warning_count: int = 0,
    sql_server_cores: int = 4,
    sql_server_edition: str = "Standard",
    _: dict = require_role(UserRole.VIEWER),
) -> JSONResponse:
    """Return executive ROI/risk summary from assessment object counts."""
    builder = ExecutiveReportBuilder()
    report = builder.build(
        project_name=project_name,
        source_database=source_database,
        total_objects=total_objects,
        auto_convertible=auto_convertible,
        partial=partial,
        unsupported=unsupported,
        risky=risky,
        blocker_count=blocker_count,
        warning_count=warning_count,
        sql_server_cores=sql_server_cores,
        sql_server_edition=sql_server_edition,
    )
    return JSONResponse(content=builder.to_dict(report))
