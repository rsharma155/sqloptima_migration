"""
Module: apps/api/routers/validation_router.py
Purpose: Validation endpoints — run L1–L3 validation levels against a migration
         job, persist results, and export reports in JSON/CSV/HTML.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from application.validation_service import ValidationService
from apps.api.connection_store import get_decrypted_password, get_entry
from apps.api.middleware.auth import UserRole, require_role
from domains.validation.validation_engine import ValidationEngine, ValidationReport
from infrastructure.metadata_db.session import AsyncSessionFactory
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["validation"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ValidationRequest(BaseModel):
    job_id: UUID
    source_connection_id: UUID
    target_connection_id: UUID
    tables: list[dict[str, Any]]


class LeveledValidationRequest(BaseModel):
    source_connection_id: UUID
    target_connection_id: UUID
    tables: list[dict[str, Any]] = Field(default_factory=list)
    levels: list[int] = Field(default_factory=lambda: [1, 2, 3])
    pk_column: str = "id"
    sample_pct: float = Field(default=1.0, ge=0.01, le=100.0)
    # For L3: supply (pk_start, pk_end) pairs
    chunks: list[list[Any]] | None = None


class ValidationRunSummary(BaseModel):
    run_id: str
    level: int
    status: str
    pass_count: int
    fail_count: int
    started_at: str | None
    completed_at: str | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_connectors(source_id: str, target_id: str):  # type: ignore[no-untyped-def]
    """Build and return (source_connector, target_connector) from connection store."""
    from infrastructure.postgres.postgres_connector import (
        PostgresConnectionConfig,
        PostgresConnector,
    )
    from infrastructure.sqlserver.sqlserver_connector import (
        SqlServerConnector,
        sqlserver_config_from_entry,
    )

    src_entry = get_entry(source_id)
    tgt_entry = get_entry(target_id)
    if not src_entry or not tgt_entry:
        raise HTTPException(status_code=404, detail="Source or target connection not found")

    source_connector = SqlServerConnector(
        sqlserver_config_from_entry(src_entry, password=get_decrypted_password(src_entry))
    )
    target_connector = PostgresConnector(
        PostgresConnectionConfig(
            host=tgt_entry["host"],
            port=int(tgt_entry.get("port", 5432)),
            database=tgt_entry["database"],
            username=tgt_entry.get("username", ""),
            password=get_decrypted_password(tgt_entry),
        )
    )
    return source_connector, target_connector


def _run_to_summary(run: Any) -> ValidationRunSummary:
    return ValidationRunSummary(
        run_id=str(run.validation_run_id),
        level=run.level,
        status=run.status,
        pass_count=run.pass_count or 0,
        fail_count=run.fail_count or 0,
        started_at=run.started_at.isoformat() if run.started_at else None,
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
    )


# ---------------------------------------------------------------------------
# Legacy endpoint (L1 + schema, no persistence)
# ---------------------------------------------------------------------------


@router.post("/validate", response_model=ValidationReport)
async def validate_migration(
    req: ValidationRequest,
    _: dict = require_role(UserRole.OPERATOR),
) -> ValidationReport:
    """Run L1 + schema validation without persistence (backwards-compatible)."""
    source_connector, target_connector = _get_connectors(
        str(req.source_connection_id), str(req.target_connection_id)
    )
    await source_connector.connect()
    await target_connector.connect()
    engine = ValidationEngine()
    try:
        report = await engine.validate_migration(
            source_connector=source_connector,
            target_connector=target_connector,
            tables=req.tables,
        )
        logger.info(
            "validation_completed",
            tables=len(req.tables),
            overall_status=report.overall_status,
        )
        return report
    except Exception as exc:
        logger.error("validation_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"Validation failed: {exc}") from exc
    finally:
        await source_connector.disconnect()
        await target_connector.disconnect()


# ---------------------------------------------------------------------------
# Level-specific validation with persistence
# ---------------------------------------------------------------------------


@router.post("/jobs/{job_id}/validate", response_model=list[ValidationRunSummary])
async def run_validation_levels(
    job_id: UUID,
    req: LeveledValidationRequest,
    _: dict = require_role(UserRole.OPERATOR),
) -> list[ValidationRunSummary]:
    """Run one or more L1–L3 validation levels; persist each run to the DB.

    Level 1 — row-count comparison
    Level 2 — aggregate (MIN/MAX/SUM) comparison
    Level 3 — per-chunk count + aggregate (supply ``chunks`` field)

    For lightweight row spot-checks use ``POST /jobs/{job_id}/row-samples``.
    """
    source_connector, target_connector = _get_connectors(
        str(req.source_connection_id), str(req.target_connection_id)
    )
    await source_connector.connect()
    await target_connector.connect()

    chunks = [tuple(c) for c in req.chunks] if req.chunks else None

    try:
        async with AsyncSessionFactory() as session:
            svc = ValidationService(session)
            runs = await svc.run_all_levels(
                job_id=str(job_id),
                source_connector=source_connector,
                target_connector=target_connector,
                tables=req.tables,
                levels=req.levels,
                chunks=chunks,
                pk_column=req.pk_column,
                sample_pct=req.sample_pct,
            )
            await session.commit()
        return [_run_to_summary(r) for r in runs]
    except Exception as exc:
        logger.error("leveled_validation_failed", job_id=str(job_id), error=str(exc))
        raise HTTPException(
            status_code=502, detail=f"Validation failed: {exc}"
        ) from exc
    finally:
        await source_connector.disconnect()
        await target_connector.disconnect()


class RowSampleRequest(BaseModel):
    source_connection_id: UUID
    target_connection_id: UUID
    table_name: str
    source_schema: str = "dbo"
    target_schema: str = "public"
    limit: int = Field(default=10, ge=1, le=100)


@router.post("/jobs/{job_id}/row-samples")
async def compare_row_samples(
    job_id: UUID,
    req: RowSampleRequest,
    _: dict = require_role(UserRole.VIEWER),
) -> dict[str, Any]:
    """Fetch top N rows from source and target sorted by PK (or first column)."""
    from application.go_engine_migration.target_table_provisioner import _fetch_pk_columns
    from apps.api.connection_store import get_entry
    from domains.migration.column_type_override import (
        fetch_source_rows_top_n_safe,
        load_resolved_overrides_from_job,
    )

    source_connector, target_connector = _get_connectors(
        str(req.source_connection_id), str(req.target_connection_id),
    )
    src_entry = get_entry(str(req.source_connection_id))
    source_database = (src_entry or {}).get("database", "")
    job = None
    type_overrides = None
    try:
        from application.migration_service import get_job

        job = get_job(job_id)
        if job:
            type_overrides = load_resolved_overrides_from_job(job) or None
    except Exception:
        type_overrides = None

    await source_connector.connect()
    await target_connector.connect()
    try:
        pk_cols = await _fetch_pk_columns(
            source_connector, req.source_schema, req.table_name,
        )
        sort_col = pk_cols[0] if pk_cols else None
        if not sort_col:
            col_rows = await source_connector.execute(
                """
                SELECT TOP 1 c.name AS column_name
                FROM sys.columns c
                WHERE c.object_id = OBJECT_ID(?)
                ORDER BY c.column_id
                """,
                {"full_name": f"{req.source_schema}.{req.table_name}"},
            )
            sort_col = col_rows[0]["column_name"] if col_rows else "1"

        if source_database:
            src_rows = await fetch_source_rows_top_n_safe(
                source_connector,
                req.source_schema,
                req.table_name,
                database=source_database,
                limit=req.limit,
                order_column=sort_col,
                resolved_overrides=type_overrides,
            )
        else:
            src_rows = await source_connector.execute(
                f"SELECT TOP {req.limit} * FROM [{req.source_schema}].[{req.table_name}] "
                f"ORDER BY [{sort_col}]"
            )
            src_rows = [dict(r) for r in src_rows]
        tgt_rows = await target_connector.execute(
            f'SELECT * FROM "{req.target_schema}"."{req.table_name}" '
            f'ORDER BY "{sort_col}" LIMIT {req.limit}'
        )

        def _serialize(rows: list[dict]) -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            for row in rows:
                out.append({
                    k: (str(v) if v is not None else None)
                    for k, v in row.items()
                })
            return out

        columns = list(src_rows[0].keys()) if src_rows else (
            list(tgt_rows[0].keys()) if tgt_rows else []
        )
        return {
            "job_id": str(job_id),
            "table_name": req.table_name,
            "source_schema": req.source_schema,
            "target_schema": req.target_schema,
            "sort_column": sort_col,
            "sort_column_type": "primary_key" if pk_cols else "first_column",
            "columns": columns,
            "source_rows": _serialize(src_rows),
            "target_rows": _serialize(tgt_rows),
            "source_count": len(src_rows),
            "target_count": len(tgt_rows),
        }
    except Exception as exc:
        logger.error("row_sample_compare_failed", job_id=str(job_id), error=str(exc))
        raise HTTPException(status_code=502, detail=f"Row sample compare failed: {exc}") from exc
    finally:
        await source_connector.disconnect()
        await target_connector.disconnect()


# ---------------------------------------------------------------------------
# Validation run queries
# ---------------------------------------------------------------------------


@router.get("/jobs/{job_id}/validation-runs", response_model=list[ValidationRunSummary])
async def list_validation_runs(
    job_id: UUID,
    _: dict = require_role(UserRole.VIEWER),
) -> list[ValidationRunSummary]:
    """Return all persisted validation runs for *job_id*."""
    async with AsyncSessionFactory() as session:
        svc = ValidationService(session)
        runs = await svc.list_runs(str(job_id))
    return [_run_to_summary(r) for r in runs]


@router.get("/validation-runs/{run_id}/report")
async def get_validation_report(
    run_id: UUID,
    fmt: str = Query(default="json", pattern="^(json|csv|html)$"),
    _: dict = require_role(UserRole.VIEWER),
) -> Any:
    """Export a stored validation run report as JSON, CSV, or HTML.

    Use ``?fmt=json`` (default), ``?fmt=csv``, or ``?fmt=html``.
    """
    async with AsyncSessionFactory() as session:
        svc = ValidationService(session)
        try:
            content = await svc.get_report(str(run_id), fmt)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    if fmt == "html":
        return HTMLResponse(content=content)
    if fmt == "csv":
        return PlainTextResponse(
            content=content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="validation_{run_id}.csv"'
            },
        )
    return PlainTextResponse(content=content, media_type="application/json")
