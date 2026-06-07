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
    TableAssessment,
)
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


class MigrationReadinessError(ValueError):
    """Raised when selected tables contain BLOCKER-tier issues."""


async def assess_source_schema(
    entry: dict[str, Any],
    *,
    database: str,
    schema: str,
    password: str,
) -> DatabaseAssessment:
    """Run full schema assessment against a SQL Server connection entry."""
    from infrastructure.sqlserver.sqlserver_connector import (
        SqlServerConnector,
        sqlserver_config_from_entry,
    )
    from infrastructure.sqlserver.sqlserver_discovery import SqlServerMetadataDiscovery

    connector = SqlServerConnector(
        sqlserver_config_from_entry({**entry, "database": database}, password=password)
    )
    await connector.connect()
    try:
        discovery = SqlServerMetadataDiscovery(connector)
        tables = await discovery.discover_tables(database, schema)

        cdc_enabled = False
        linked_refs: list[dict] = []
        global_temp_refs: list[dict] = []
        agent_jobs: list[dict] = []

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

        engine = AssessmentEngine()
        return engine.assess_database(
            database_name=database,
            tables=tables,
            cdc_enabled_db=cdc_enabled,
            linked_server_refs=linked_refs,
            global_temp_table_refs=global_temp_refs,
            agent_jobs=agent_jobs,
        )
    finally:
        await connector.disconnect()


def table_assessments_by_name(assessment: DatabaseAssessment) -> dict[str, TableAssessment]:
    return {ta.table_name.lower(): ta for ta in assessment.tables}


def selected_table_blockers(
    assessment: DatabaseAssessment,
    table_names: list[str],
) -> list[tuple[str, list[str]]]:
    """Return (table_name, blocker_messages) for BLOCKER-tier selected tables."""
    by_name = table_assessments_by_name(assessment)
    blocked: list[tuple[str, list[str]]] = []
    for name in table_names:
        ta = by_name.get(name.lower())
        if ta is None:
            blocked.append((name, [f"Table {name!r} was not found in assessment results"]))
            continue
        if ta.migration_tier == MigrationTier.BLOCKER:
            messages = ta.blockers or [
                f"Table has BLOCKER complexity (score {ta.complexity_score}/100)"
            ]
            blocked.append((name, messages))
    return blocked


def assert_tables_ready_for_migration(
    assessment: DatabaseAssessment,
    table_names: list[str],
) -> None:
    """Raise MigrationReadinessError if any selected table is BLOCKER-tier."""
    blocked = selected_table_blockers(assessment, table_names)
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


async def validate_migration_tables_ready(
    connection_id: UUID,
    *,
    database: str,
    schema: str,
    table_names: list[str],
    entry: dict[str, Any],
    password: str,
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
    assert_tables_ready_for_migration(assessment, table_names)
