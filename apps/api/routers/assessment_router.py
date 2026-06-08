"""
Module: apps/api/routers/assessment_router.py
Purpose: REST endpoints for database migration assessment (SAFE/WARNING/BLOCKER
         ratings, complexity scores, and migration time estimates).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from apps.api.connection_store import get_decrypted_password, get_entry
from apps.api.middleware.auth import UserRole, require_role
from domains.assessment.assessment_engine import (
    AssessmentEngine,
    DatabaseAssessment,
    RoutineAssessment,
    TableAssessment,
)
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["assessment"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class RoutineTableDependencyOut(BaseModel):
    source_schema: str
    object_name: str
    object_type: str
    target_schema: str
    target_object: str
    status: str


class AssessmentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    connection_id: UUID
    database: str = ""
    schema_name: str = Field(default="dbo", alias="schema")
    target_connection_id: UUID | None = None
    target_schema: str | None = None
    selected_tables: list[str] = Field(default_factory=list)


class TableAssessmentOut(BaseModel):
    table_name: str
    schema_name: str
    migration_tier: str
    complexity_score: int
    estimated_minutes: float
    row_count_estimate: int
    lob_columns: list[str]
    ci_collation_columns: list[str]
    blocker_types: list[str]
    unsupported_type_columns: list[dict[str, str]] = Field(default_factory=list)
    blockers: list[str]
    warnings: list[str]
    prerequisites: list[str]


class RoutineAssessmentOut(BaseModel):
    routine_name: str
    schema_name: str
    object_type: str
    migration_tier: str
    complexity_score: int
    estimated_minutes: float
    conversion_difficulty: str
    detected_patterns: list[str]
    blockers: list[str]
    warnings: list[str]
    prerequisites: list[str]
    table_dependencies: list[RoutineTableDependencyOut] = Field(default_factory=list)
    missing_target_tables: list[str] = Field(default_factory=list)


class DatabaseAssessmentOut(BaseModel):
    database_name: str
    overall_tier: str
    total_tables: int
    total_routines: int = 0
    safe_count: int
    warning_count: int
    blocker_count: int
    routine_safe_count: int = 0
    routine_warning_count: int = 0
    routine_blocker_count: int = 0
    estimated_total_minutes: float
    cdc_enabled_db: bool
    global_prerequisites: list[str]
    linked_server_refs: list[dict[str, Any]]
    global_temp_table_refs: list[dict[str, Any]]
    agent_jobs: list[dict[str, Any]]
    tables: list[TableAssessmentOut]
    routines: list[RoutineAssessmentOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_table_out(ta: TableAssessment) -> TableAssessmentOut:
    return TableAssessmentOut(
        table_name=ta.table_name,
        schema_name=ta.schema_name,
        migration_tier=ta.migration_tier.value,
        complexity_score=ta.complexity_score,
        estimated_minutes=ta.estimated_minutes,
        row_count_estimate=ta.row_count_estimate,
        lob_columns=ta.lob_columns,
        ci_collation_columns=ta.ci_collation_columns,
        blocker_types=ta.blocker_types,
        unsupported_type_columns=ta.unsupported_type_columns,
        blockers=ta.blockers,
        warnings=ta.warnings,
        prerequisites=ta.prerequisites,
    )


def _to_routine_out(ra: RoutineAssessment) -> RoutineAssessmentOut:
    return RoutineAssessmentOut(
        routine_name=ra.routine_name,
        schema_name=ra.schema_name,
        object_type=ra.object_type,
        migration_tier=ra.migration_tier.value,
        complexity_score=ra.complexity_score,
        estimated_minutes=ra.estimated_minutes,
        conversion_difficulty=ra.conversion_difficulty,
        detected_patterns=ra.detected_patterns,
        blockers=ra.blockers,
        warnings=ra.warnings,
        prerequisites=ra.prerequisites,
        table_dependencies=[
            RoutineTableDependencyOut(**dep) for dep in ra.table_dependencies
        ],
        missing_target_tables=ra.missing_target_tables,
    )


def _to_db_out(da: DatabaseAssessment) -> DatabaseAssessmentOut:
    return DatabaseAssessmentOut(
        database_name=da.database_name,
        overall_tier=da.overall_tier.value,
        total_tables=da.total_tables,
        total_routines=da.total_routines,
        safe_count=da.safe_count,
        warning_count=da.warning_count,
        blocker_count=da.blocker_count,
        routine_safe_count=da.routine_safe_count,
        routine_warning_count=da.routine_warning_count,
        routine_blocker_count=da.routine_blocker_count,
        estimated_total_minutes=da.estimated_total_minutes,
        cdc_enabled_db=da.cdc_enabled_db,
        global_prerequisites=da.global_prerequisites,
        linked_server_refs=da.linked_server_refs,
        global_temp_table_refs=da.global_temp_table_refs,
        agent_jobs=da.agent_jobs,
        tables=[_to_table_out(t) for t in da.tables],
        routines=[_to_routine_out(r) for r in da.routines],
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/assess", response_model=DatabaseAssessmentOut)
async def assess_database(
    req: AssessmentRequest,
    _: dict = require_role(UserRole.OPERATOR),
) -> DatabaseAssessmentOut:
    """Run a full migration assessment against a SQL Server source connection.

    Returns SAFE/WARNING/BLOCKER tiers per table along with complexity scores
    and estimated migration times.
    """
    from infrastructure.sqlserver.sqlserver_connector import (
        SqlServerConnector,
        sqlserver_config_from_entry,
    )
    from infrastructure.sqlserver.sqlserver_discovery import SqlServerMetadataDiscovery

    entry = get_entry(str(req.connection_id))
    if not entry:
        raise HTTPException(status_code=404, detail="Connection not found")

    database = req.database or entry.get("database", "")
    password = get_decrypted_password(entry)

    if not database:
        raise HTTPException(status_code=400, detail="database is required")

    from application.migration_readiness_service import assess_source_schema

    target_entry = None
    target_password = None
    if req.target_connection_id is not None:
        target_entry = get_entry(str(req.target_connection_id))
        if not target_entry:
            raise HTTPException(status_code=404, detail="Target connection not found")
        target_password = get_decrypted_password(target_entry)

    try:
        db_assessment = await assess_source_schema(
            entry,
            database=database,
            schema=req.schema_name,
            password=password,
            target_entry=target_entry,
            target_password=target_password,
            target_schema=req.target_schema,
            selected_tables=req.selected_tables or None,
        )
        logger.info(
            "assessment_complete",
            database=database,
            schema=req.schema_name,
            overall_tier=db_assessment.overall_tier,
            tables=db_assessment.total_tables,
            routines=db_assessment.total_routines,
        )
        return _to_db_out(db_assessment)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("assessment_failed", database=database, error=str(exc))
        raise HTTPException(
            status_code=502, detail=f"Assessment failed: {exc}"
        ) from exc


@router.post("/assess/table", response_model=TableAssessmentOut)
async def assess_single_table(
    connection_id: UUID,
    database: str,
    schema: str,
    table_name: str,
    _: dict = require_role(UserRole.OPERATOR),
) -> TableAssessmentOut:
    """Assess a single table without running full database discovery."""
    from infrastructure.sqlserver.sqlserver_connector import (
        SqlServerConnector,
        sqlserver_config_from_entry,
    )
    from infrastructure.sqlserver.sqlserver_discovery import SqlServerMetadataDiscovery

    entry = get_entry(str(connection_id))
    if not entry:
        raise HTTPException(status_code=404, detail="Connection not found")

    connector = SqlServerConnector(
        sqlserver_config_from_entry(
            {**entry, "database": database},
            password=get_decrypted_password(entry),
        )
    )
    await connector.connect()
    try:
        discovery = SqlServerMetadataDiscovery(connector)
        tables = await discovery.discover_tables(database, schema)
        matched = [t for t in tables if t.object_name == table_name]
        if not matched:
            raise HTTPException(
                status_code=404,
                detail=f"Table {schema}.{table_name} not found in {database}",
            )
        engine = AssessmentEngine()
        return _to_table_out(engine.assess_table(matched[0]))
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("table_assessment_failed", table=table_name, error=str(exc))
        raise HTTPException(
            status_code=502, detail=f"Table assessment failed: {exc}"
        ) from exc
    finally:
        await connector.disconnect()
