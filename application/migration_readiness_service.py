# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""Migration readiness assessment — shared by /assess and pre-migration validation."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from domains.assessment.assessment_engine import (
    AssessmentEngine,
    DatabaseAssessment,
    MigrationTier,
    RoutineAssessment,
    TableAssessment,
)
from domains.assessment.routine_dependency_checker import enrich_routine_assessments
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


def _recompute_assessment_tiers(assessment: DatabaseAssessment) -> None:
    """Refresh aggregate tier counts after routine dependency enrichment."""
    safe = sum(1 for a in assessment.tables if a.migration_tier == MigrationTier.SAFE)
    warning = sum(1 for a in assessment.tables if a.migration_tier == MigrationTier.WARNING)
    blocker = sum(1 for a in assessment.tables if a.migration_tier == MigrationTier.BLOCKER)
    routine_safe = sum(
        1 for a in assessment.routines if a.migration_tier == MigrationTier.SAFE
    )
    routine_warning = sum(
        1 for a in assessment.routines if a.migration_tier == MigrationTier.WARNING
    )
    routine_blocker = sum(
        1 for a in assessment.routines if a.migration_tier == MigrationTier.BLOCKER
    )
    assessment.safe_count = safe
    assessment.warning_count = warning
    assessment.blocker_count = blocker
    assessment.routine_safe_count = routine_safe
    assessment.routine_warning_count = routine_warning
    assessment.routine_blocker_count = routine_blocker
    if blocker > 0 or routine_blocker > 0:
        assessment.overall_tier = MigrationTier.BLOCKER
    elif warning > 0 or routine_warning > 0:
        assessment.overall_tier = MigrationTier.WARNING
    else:
        assessment.overall_tier = MigrationTier.SAFE


class MigrationReadinessError(ValueError):
    """Raised when selected tables contain BLOCKER-tier issues."""


async def assess_source_schema(
    entry: dict[str, Any],
    *,
    database: str,
    schema: str,
    password: str,
    target_entry: dict[str, Any] | None = None,
    target_password: str | None = None,
    target_schema: str | None = None,
    selected_tables: list[str] | None = None,
) -> DatabaseAssessment:
    """Run full schema assessment against a SQL Server connection entry."""
    from infrastructure.postgres.postgres_connector import (
        PostgresConnector,
        postgres_config_from_entry,
    )
    from infrastructure.sqlserver.sqlserver_connector import (
        SqlServerConnector,
        sqlserver_config_from_entry,
    )
    from infrastructure.sqlserver.sqlserver_discovery import SqlServerMetadataDiscovery

    connector = SqlServerConnector(
        sqlserver_config_from_entry({**entry, "database": database}, password=password)
    )
    await connector.connect()
    target_connector: PostgresConnector | None = None
    try:
        discovery = SqlServerMetadataDiscovery(connector)
        tables = await discovery.discover_tables(database, schema)
        procedures = await discovery.discover_procedures(database, schema)
        functions = await discovery.discover_functions(database, schema)
        routines = [*procedures, *functions]

        cdc_enabled = False
        linked_refs: list[dict] = []
        global_temp_refs: list[dict] = []
        agent_jobs: list[dict] = []
        routine_dep_rows: list[dict] = []

        try:
            cdc_info = await discovery.discover_cdc_status(database, schema)
            cdc_enabled = cdc_info.get("db_cdc_enabled", False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cdc_status_query_failed", error=str(exc))

        try:
            linked_refs = await discovery.discover_linked_server_refs(database)
        except Exception as exc:  # noqa: BLE001
            logger.warning("linked_server_query_failed", error=str(exc))

        try:
            global_temp_refs = await discovery.discover_global_temp_table_refs(database)
        except Exception as exc:  # noqa: BLE001
            logger.warning("global_temp_table_query_failed", error=str(exc))

        try:
            agent_jobs = await discovery.discover_agent_jobs(database)
        except Exception as exc:  # noqa: BLE001
            logger.warning("agent_jobs_query_failed", error=str(exc))

        if routines:
            try:
                routine_dep_rows = await discovery.discover_routine_table_dependencies(
                    database,
                    schema,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("routine_dependency_query_failed", error=str(exc))

        engine = AssessmentEngine()
        assessment = engine.assess_database(
            database_name=database,
            tables=tables,
            routines=routines,
            cdc_enabled_db=cdc_enabled,
            linked_server_refs=linked_refs,
            global_temp_table_refs=global_temp_refs,
            agent_jobs=agent_jobs,
        )

        if assessment.routines:
            if target_entry and target_password:
                target_connector = PostgresConnector(
                    postgres_config_from_entry(target_entry, password=target_password)
                )
                await target_connector.connect()
            if routine_dep_rows:
                await enrich_routine_assessments(
                    assessment.routines,
                    dependency_rows=routine_dep_rows,
                    migration_source_schema=schema,
                    target_schema=target_schema,
                    target_connector=target_connector,
                    selected_tables=selected_tables,
                )
                _recompute_assessment_tiers(assessment)

        return assessment
    finally:
        if target_connector is not None:
            await target_connector.disconnect()
        await connector.disconnect()


def table_assessments_by_name(assessment: DatabaseAssessment) -> dict[str, TableAssessment]:
    return {ta.table_name.lower(): ta for ta in assessment.tables}


def selected_table_blockers(
    assessment: DatabaseAssessment,
    table_names: list[str],
    *,
    column_type_overrides: dict[str, str] | None = None,
) -> list[tuple[str, list[str]]]:
    """Return (table_name, blocker_messages) for BLOCKER-tier selected tables."""
    from domains.migration.column_type_override import table_blocked_after_overrides

    overrides = column_type_overrides or {}
    by_name = table_assessments_by_name(assessment)
    blocked: list[tuple[str, list[str]]] = []
    for name in table_names:
        ta = by_name.get(name.lower())
        if ta is None:
            blocked.append((name, [f"Table {name!r} was not found in assessment results"]))
            continue
        if ta.migration_tier != MigrationTier.BLOCKER:
            continue
        still_blocked, messages = table_blocked_after_overrides(ta, overrides)
        if still_blocked:
            blocked.append((name, messages))
    return blocked


def assert_tables_ready_for_migration(
    assessment: DatabaseAssessment,
    table_names: list[str],
    *,
    column_type_overrides: dict[str, str] | None = None,
) -> None:
    """Raise MigrationReadinessError if any selected table is BLOCKER-tier."""
    blocked = selected_table_blockers(
        assessment,
        table_names,
        column_type_overrides=column_type_overrides,
    )
    if not blocked:
        return
    lines = [
        f"{table}: {'; '.join(msgs)}"
        for table, msgs in blocked
    ]
    raise MigrationReadinessError(
        "Migration blocked due to critical (BLOCKER) issues on "
        f"{len(blocked)} table(s): " + " | ".join(lines)
    )


def routine_assessments_by_name(
    assessment: DatabaseAssessment,
) -> dict[str, RoutineAssessment]:
    return {ra.routine_name.lower(): ra for ra in assessment.routines}


def selected_routine_blockers(
    assessment: DatabaseAssessment,
    procedure_names: list[str],
    function_names: list[str],
) -> list[tuple[str, list[str]]]:
    """Return (routine_label, blocker_messages) for BLOCKER-tier selected routines."""
    by_name = routine_assessments_by_name(assessment)
    blocked: list[tuple[str, list[str]]] = []
    for name in procedure_names:
        ra = by_name.get(name.lower())
        label = f"procedure {name}"
        if ra is None:
            blocked.append((label, [f"Procedure {name!r} was not found in assessment results"]))
            continue
        if ra.migration_tier != MigrationTier.BLOCKER:
            continue
        blocked.append((label, ra.blockers or ["Critical blocker — manual remediation required"]))
    for name in function_names:
        ra = by_name.get(name.lower())
        label = f"function {name}"
        if ra is None:
            blocked.append((label, [f"Function {name!r} was not found in assessment results"]))
            continue
        if ra.migration_tier != MigrationTier.BLOCKER:
            continue
        blocked.append((label, ra.blockers or ["Critical blocker — manual remediation required"]))
    return blocked


def assert_routines_ready_for_migration(
    assessment: DatabaseAssessment,
    procedure_names: list[str],
    function_names: list[str],
) -> None:
    """Raise MigrationReadinessError if any selected routine is BLOCKER-tier."""
    blocked = selected_routine_blockers(assessment, procedure_names, function_names)
    if not blocked:
        return
    lines = [f"{label}: {'; '.join(msgs)}" for label, msgs in blocked]
    raise MigrationReadinessError(
        "Migration blocked due to critical (BLOCKER) issues on "
        f"{len(blocked)} routine(s): " + " | ".join(lines)
    )


async def validate_migration_tables_ready(
    connection_id: UUID,
    *,
    database: str,
    schema: str,
    table_names: list[str],
    entry: dict[str, Any],
    password: str,
    column_type_overrides: dict[str, str] | None = None,
) -> None:
    """Assess schema and reject migration when selected tables have BLOCKER issues."""
    if not table_names:
        raise MigrationReadinessError("At least one table is required")
    assessment = await assess_source_schema(
        entry,
        database=database,
        schema=schema,
        password=password,
    )
    if column_type_overrides:
        from domains.migration.column_type_override import resolve_overrides_for_tables

        resolve_overrides_for_tables(assessment, table_names, column_type_overrides)
    assert_tables_ready_for_migration(
        assessment,
        table_names,
        column_type_overrides=column_type_overrides,
    )


async def validate_migration_routines_ready(
    *,
    database: str,
    schema: str,
    procedure_names: list[str],
    function_names: list[str],
    entry: dict[str, Any],
    password: str,
    target_entry: dict[str, Any] | None = None,
    target_password: str | None = None,
    target_schema: str | None = None,
    selected_tables: list[str] | None = None,
) -> None:
    """Assess routines and reject migration when selected routines have BLOCKER issues."""
    if not procedure_names and not function_names:
        return
    assessment = await assess_source_schema(
        entry,
        database=database,
        schema=schema,
        password=password,
        target_entry=target_entry,
        target_password=target_password,
        target_schema=target_schema,
        selected_tables=selected_tables,
    )
    assert_routines_ready_for_migration(assessment, procedure_names, function_names)
