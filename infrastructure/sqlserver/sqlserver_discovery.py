"""
Module: sqlserver_discovery.py
Purpose: SQL Server metadata discovery using system catalog queries
Author: Migration Platform Team
Created: 2026-05-22
Domain: Infrastructure
Dependencies: pyodbc, sqlglot
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from typing import Any
from uuid import UUID

from infrastructure.sqlserver.sqlserver_connector import SqlServerConnector
from shared.contracts.base_connector import MetadataDiscoveryPort
from shared.kernel.database_object import (
    Column,
    DatabaseObject,
    DatabaseObjectType,
    DataType,
    Table,
)

# System catalog queries
QUERY_DATABASES = """
SELECT name AS database_name
FROM sys.databases
WHERE state = 0
ORDER BY name
"""

QUERY_SCHEMAS = """
SELECT s.name AS schema_name
FROM {database}.sys.schemas s
WHERE s.name NOT IN ('sys', 'INFORMATION_SCHEMA', 'guest', 'db_owner', 'db_accessadmin',
                     'db_securityadmin', 'db_ddladmin', 'db_backupoperator', 'db_datareader',
                     'db_datawriter', 'db_denydatareader', 'db_denydatawriter')
ORDER BY s.name
"""

QUERY_TABLES = """
SELECT
    OBJECT_SCHEMA_NAME(t.object_id) AS schema_name,
    t.name AS table_name,
    t.object_id,
    (SELECT COUNT(*) FROM {database}.sys.columns c WHERE c.object_id = t.object_id) AS column_count,
    CASE WHEN t.temporal_type > 0 THEN 1 ELSE 0 END AS is_temporal,
    CASE WHEN t.is_memory_optimized > 0 THEN 1 ELSE 0 END AS is_memory_optimized,
    p.rows AS row_count_estimate
FROM {database}.sys.tables t
INNER JOIN {database}.sys.partitions p ON t.object_id = p.object_id AND p.index_id IN (0, 1)
WHERE OBJECT_SCHEMA_NAME(t.object_id) = ?
GROUP BY t.object_id, t.name, t.temporal_type, t.is_memory_optimized, p.rows
ORDER BY t.name
"""

QUERY_COLUMNS = """
SELECT
    c.name AS column_name,
    c.column_id AS ordinal_position,
    TYPE_NAME(c.user_type_id) AS type_name,
    c.precision,
    c.scale,
    c.max_length,
    c.is_nullable,
    c.is_identity,
    c.is_computed,
    cc.definition AS computed_definition,
    dc.definition AS default_value,
    c.collation_name
FROM {database}.sys.columns c
LEFT JOIN {database}.sys.computed_columns cc ON c.object_id = cc.object_id AND c.column_id = cc.column_id
LEFT JOIN {database}.sys.default_constraints dc ON c.default_object_id = dc.object_id
WHERE c.object_id = OBJECT_ID(?)
ORDER BY c.column_id
"""

QUERY_COLUMNS_BATCH = """
SELECT
    OBJECT_SCHEMA_NAME(c.object_id) AS schema_name,
    OBJECT_NAME(c.object_id) AS table_name,
    c.name AS column_name,
    c.column_id AS ordinal_position,
    TYPE_NAME(c.user_type_id) AS type_name,
    c.precision,
    c.scale,
    c.max_length,
    c.is_nullable,
    c.is_identity,
    c.is_computed,
    cc.definition AS computed_definition,
    dc.definition AS default_value,
    c.collation_name
FROM {database}.sys.columns c
LEFT JOIN {database}.sys.computed_columns cc ON c.object_id = cc.object_id AND c.column_id = cc.column_id
LEFT JOIN {database}.sys.default_constraints dc ON c.default_object_id = dc.object_id
INNER JOIN {database}.sys.tables t ON c.object_id = t.object_id
WHERE OBJECT_SCHEMA_NAME(c.object_id) = ?
ORDER BY t.name, c.column_id
"""

QUERY_INDEXES = """
SELECT
    i.name AS index_name,
    i.type_desc AS index_type,
    i.is_unique,
    i.is_primary_key,
    i.filter_definition,
    STRING_AGG(ic.key_ordinal, ',') WITHIN GROUP (ORDER BY ic.key_ordinal) AS key_ordinals,
    STRING_AGG(c.name, ',') WITHIN GROUP (ORDER BY ic.key_ordinal) AS column_names,
    ic.is_included_column
FROM {database}.sys.indexes i
INNER JOIN {database}.sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id
INNER JOIN {database}.sys.columns c ON i.object_id = c.object_id AND ic.column_id = c.column_id
WHERE i.object_id = OBJECT_ID(?)
    AND i.is_primary_key = 0
    AND i.type NOT IN (0, 3)
GROUP BY i.name, i.type_desc, i.is_unique, i.is_primary_key, i.filter_definition
ORDER BY i.name
"""

QUERY_FOREIGN_KEYS = """
SELECT
    fk.name AS fk_name,
    OBJECT_NAME(fk.parent_object_id) AS parent_table,
    COL_NAME(fkc.parent_object_id, fkc.parent_column_id) AS parent_column,
    OBJECT_NAME(fk.referenced_object_id) AS referenced_table,
    COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id) AS referenced_column,
    fk.delete_referential_action_desc AS delete_action,
    fk.update_referential_action_desc AS update_action,
    fk.is_disabled
FROM {database}.sys.foreign_keys fk
INNER JOIN {database}.sys.foreign_key_columns fkc
    ON fk.object_id = fkc.constraint_object_id
WHERE fk.parent_object_id = OBJECT_ID(?)
ORDER BY fk.name, fkc.constraint_column_id
"""

QUERY_VIEWS = """
SELECT
    OBJECT_SCHEMA_NAME(v.object_id) AS schema_name,
    v.name AS view_name,
    m.definition
FROM {database}.sys.views v
INNER JOIN {database}.sys.sql_modules m ON v.object_id = m.object_id
WHERE OBJECT_SCHEMA_NAME(v.object_id) = ?
ORDER BY v.name
"""

QUERY_PROCEDURES = """
SELECT
    OBJECT_SCHEMA_NAME(p.object_id) AS schema_name,
    p.name AS procedure_name,
    m.definition
FROM {database}.sys.procedures p
INNER JOIN {database}.sys.sql_modules m ON p.object_id = m.object_id
WHERE OBJECT_SCHEMA_NAME(p.object_id) = ?
ORDER BY p.name
"""

QUERY_FUNCTIONS = """
SELECT
    OBJECT_SCHEMA_NAME(f.object_id) AS schema_name,
    f.name AS function_name,
    f.type_desc,
    m.definition
FROM {database}.sys.objects f
INNER JOIN {database}.sys.sql_modules m ON f.object_id = m.object_id
WHERE f.type IN ('FN', 'IF', 'TF', 'FS', 'FT')
    AND OBJECT_SCHEMA_NAME(f.object_id) = ?
ORDER BY f.name
"""

QUERY_DEPENDENCIES = """
SELECT
    OBJECT_SCHEMA_NAME(referencing_id) AS referencing_schema,
    OBJECT_NAME(referencing_id) AS referencing_object,
    referenced_entity_name AS referenced_object,
    referenced_schema_name AS referenced_schema,
    referenced_class_desc
FROM {database}.sys.sql_expression_dependencies
WHERE OBJECT_SCHEMA_NAME(referencing_id) NOT IN ('sys', 'INFORMATION_SCHEMA')
    AND referenced_schema_name NOT IN ('sys', 'INFORMATION_SCHEMA')
    AND referencing_id > 0
"""

QUERY_TRIGGERS = """
SELECT
    OBJECT_SCHEMA_NAME(t.parent_id) AS schema_name,
    OBJECT_NAME(t.parent_id) AS parent_table,
    t.name AS trigger_name,
    m.definition
FROM {database}.sys.triggers t
INNER JOIN {database}.sys.sql_modules m ON t.object_id = m.object_id
WHERE OBJECT_SCHEMA_NAME(t.parent_id) = ?
ORDER BY t.name
"""

# ---------------------------------------------------------------------------
# Phase-4 enhancement queries
# ---------------------------------------------------------------------------

QUERY_CDC_DB_STATUS = """
SELECT is_cdc_enabled
FROM {database}.sys.databases
WHERE name = ?
"""

QUERY_CDC_TABLE_STATUS = """
SELECT
    OBJECT_SCHEMA_NAME(t.object_id) AS schema_name,
    t.name AS table_name,
    t.is_tracked_by_cdc
FROM {database}.sys.tables t
WHERE OBJECT_SCHEMA_NAME(t.object_id) = ?
ORDER BY t.name
"""

QUERY_LINKED_SERVER_REFS = """
SELECT
    OBJECT_SCHEMA_NAME(d.referencing_id)        AS referencing_schema,
    OBJECT_NAME(d.referencing_id)               AS referencing_object,
    d.referenced_server_name                     AS referenced_server,
    d.referenced_database_name                   AS referenced_database,
    d.referenced_entity_name                     AS referenced_entity
FROM {database}.sys.sql_expression_dependencies d
WHERE d.referenced_server_name IS NOT NULL
  AND OBJECT_SCHEMA_NAME(d.referencing_id) NOT IN ('sys', 'INFORMATION_SCHEMA')
ORDER BY d.referenced_server_name, OBJECT_NAME(d.referencing_id)
"""

QUERY_GLOBAL_TEMP_TABLE_REFS = """
SELECT
    OBJECT_SCHEMA_NAME(m.object_id) AS schema_name,
    OBJECT_NAME(m.object_id)        AS object_name,
    o.type_desc                      AS object_type
FROM {database}.sys.sql_modules m
INNER JOIN {database}.sys.objects o ON m.object_id = o.object_id
WHERE m.definition LIKE '%##%'
  AND OBJECT_SCHEMA_NAME(m.object_id) NOT IN ('sys', 'INFORMATION_SCHEMA')
ORDER BY OBJECT_NAME(m.object_id)
"""

# SQL Server Agent jobs — requires VIEW SERVER STATE or sysadmin; graceful fallback
# if msdb is unavailable or permissions are insufficient.
QUERY_AGENT_JOBS = """
SELECT
    j.name        AS job_name,
    j.enabled     AS is_enabled,
    s.step_name,
    s.command     AS step_command
FROM msdb.dbo.sysjobs      j
INNER JOIN msdb.dbo.sysjobsteps s ON j.job_id = s.job_id
WHERE s.command LIKE ?
ORDER BY j.name, s.step_id
"""


class SqlServerMetadataDiscovery(MetadataDiscoveryPort):
    """SQL Server metadata discovery implementation."""

    def __init__(self, connector: SqlServerConnector):
        self._connector = connector
        self._database: str | None = None

    def _q(self, query: str) -> str:
        """Format query with database name."""
        return query.replace("{database}", self._database)

    async def discover_databases(self) -> list[DatabaseObject]:
        results = await self._connector.execute(QUERY_DATABASES)
        return [
            DatabaseObject(
                object_type=DatabaseObjectType.DATABASE,
                database_name=r["database_name"],
                schema_name="",
                object_name=r["database_name"],
            )
            for r in results
        ]

    async def discover_schemas(self, database: str) -> list[DatabaseObject]:
        self._database = database
        results = await self._connector.execute(self._q(QUERY_SCHEMAS))
        return [
            DatabaseObject(
                object_type=DatabaseObjectType.SCHEMA,
                database_name=database,
                schema_name=r["schema_name"],
                object_name=r["schema_name"],
            )
            for r in results
        ]

    async def discover_tables(self, database: str, schema: str) -> list[Table]:
        self._database = database
        results = await self._connector.execute(self._q(QUERY_TABLES), {"schema": schema})
        if not results:
            return []

        table_names = [r["table_name"] for r in results]
        table_map = {r["table_name"]: r for r in results}

        col_results = await self._connector.execute(
            self._q(QUERY_COLUMNS_BATCH), {"schema": schema}
        )

        columns_by_table: dict[str, list[Column]] = {}
        for cr in col_results:
            tbl = cr["table_name"]
            if tbl not in columns_by_table:
                columns_by_table[tbl] = []
            dt = DataType(
                type_name=cr["type_name"],
                precision=cr["precision"],
                scale=cr["scale"],
                max_length=cr["max_length"],
                is_nullable=bool(cr["is_nullable"]),
            )
            columns_by_table[tbl].append(
                Column(
                    table_id=UUID(int=0),
                    column_name=cr["column_name"],
                    ordinal_position=cr["ordinal_position"],
                    data_type=dt,
                    is_identity=bool(cr["is_identity"]),
                    is_computed=bool(cr["is_computed"]),
                    computed_definition=cr.get("computed_definition"),
                    default_value=cr.get("default_value"),
                    is_nullable=bool(cr["is_nullable"]),
                    collation_name=cr.get("collation_name"),
                )
            )

        tables = []
        for name in table_names:
            r = table_map[name]
            columns = columns_by_table.get(name, [])
            table = Table(
                database_name=database,
                schema_name=schema,
                object_name=r["table_name"],
                row_count_estimate=r["row_count_estimate"],
                is_temporal=bool(r["is_temporal"]),
                is_memory_optimized=bool(r["is_memory_optimized"]),
                columns=columns,
                index_count=len(columns),
            )
            tables.append(table)
        return tables

    async def discover_views(self, database: str, schema: str) -> list[DatabaseObject]:
        self._database = database
        results = await self._connector.execute(self._q(QUERY_VIEWS), {"schema": schema})
        return [
            DatabaseObject(
                object_type=DatabaseObjectType.VIEW,
                database_name=database,
                schema_name=r["schema_name"],
                object_name=r["view_name"],
                source_definition=r["definition"],
            )
            for r in results
        ]

    async def discover_procedures(self, database: str, schema: str) -> list[DatabaseObject]:
        self._database = database
        results = await self._connector.execute(self._q(QUERY_PROCEDURES), {"schema": schema})
        return [
            DatabaseObject(
                object_type=DatabaseObjectType.PROCEDURE,
                database_name=database,
                schema_name=r["schema_name"],
                object_name=r["procedure_name"],
                source_definition=r["definition"],
            )
            for r in results
        ]

    async def discover_functions(self, database: str, schema: str) -> list[DatabaseObject]:
        self._database = database
        results = await self._connector.execute(self._q(QUERY_FUNCTIONS), {"schema": schema})
        return [
            DatabaseObject(
                object_type=DatabaseObjectType.FUNCTION,
                database_name=database,
                schema_name=r["schema_name"],
                object_name=r["function_name"],
                source_definition=r["definition"],
            )
            for r in results
        ]

    async def discover_indexes(self, database: str, schema: str, table: str) -> list[DatabaseObject]:
        self._database = database
        full_name = f"{schema}.{table}"
        results = await self._connector.execute(self._q(QUERY_INDEXES), {"full_name": full_name})
        return [
            DatabaseObject(
                object_type=DatabaseObjectType.INDEX,
                database_name=database,
                schema_name=schema,
                object_name=r["index_name"],
                properties={
                    "index_type": r["index_type"],
                    "is_unique": bool(r["is_unique"]),
                    "is_primary_key": bool(r["is_primary_key"]),
                    "filter_definition": r["filter_definition"],
                    "columns": r["column_names"],
                },
            )
            for r in results
        ]

    async def discover_foreign_keys(self, database: str, schema: str, table: str) -> list[DatabaseObject]:
        self._database = database
        full_name = f"{schema}.{table}"
        results = await self._connector.execute(self._q(QUERY_FOREIGN_KEYS), {"full_name": full_name})
        return [
            DatabaseObject(
                object_type=DatabaseObjectType.FOREIGN_KEY,
                database_name=database,
                schema_name=schema,
                object_name=r["fk_name"],
                properties=dict(r),
            )
            for r in results
        ]

    async def discover_dependencies(self, database: str) -> list[dict[str, Any]]:
        self._database = database
        return await self._connector.execute(self._q(QUERY_DEPENDENCIES))

    async def get_schema_ddl(self, database: str, schema: str) -> dict[str, str]:
        tables = await self.discover_tables(database, schema)
        views = await self.discover_views(database, schema)
        ddl_map: dict[str, str] = {}
        for t in tables:
            ddl_map[t.fully_qualified_name] = t.source_definition or ""
        for v in views:
            ddl_map[v.fully_qualified_name] = v.source_definition or ""
        return ddl_map

    # ------------------------------------------------------------------
    # Phase-4 enhancement methods
    # ------------------------------------------------------------------

    async def discover_cdc_status(self, database: str, schema: str) -> dict[str, Any]:
        """Return CDC enablement state for the database and each table in *schema*.

        Returns a dict::

            {
                "db_cdc_enabled": bool,
                "tables": {
                    "table_name": bool,  # True if tracked by CDC
                    ...
                }
            }
        """
        self._database = database

        db_rows = await self._connector.execute(
            self._q(QUERY_CDC_DB_STATUS), {"db_name": database}
        )
        db_enabled: bool = bool(db_rows[0]["is_cdc_enabled"]) if db_rows else False

        tbl_rows = await self._connector.execute(
            self._q(QUERY_CDC_TABLE_STATUS), {"schema": schema}
        )
        tables_map: dict[str, bool] = {
            r["table_name"]: bool(r["is_tracked_by_cdc"]) for r in tbl_rows
        }
        return {"db_cdc_enabled": db_enabled, "tables": tables_map}

    async def discover_linked_server_refs(
        self, database: str
    ) -> list[dict[str, Any]]:
        """Return objects that reference a linked server in their definition."""
        self._database = database
        rows = await self._connector.execute(self._q(QUERY_LINKED_SERVER_REFS))
        return [dict(r) for r in rows]

    async def discover_global_temp_table_refs(
        self, database: str
    ) -> list[dict[str, Any]]:
        """Return procedures/functions/views whose definition references ## tables."""
        self._database = database
        rows = await self._connector.execute(self._q(QUERY_GLOBAL_TEMP_TABLE_REFS))
        return [dict(r) for r in rows]

    async def discover_agent_jobs(self, database: str) -> list[dict[str, Any]]:
        """Return SQL Server Agent job steps whose command references *database*.

        Queries msdb.dbo.sysjobs + sysjobsteps filtering by database name in the
        step command.  Returns an empty list (not an error) if msdb is inaccessible
        or the login lacks VIEW SERVER STATE permission — both are common in
        restricted environments.
        """
        self._database = database
        try:
            pattern = f"%{database}%"
            rows = await self._connector.execute(QUERY_AGENT_JOBS, {"pattern": pattern})
            return [dict(r) for r in rows]
        except Exception:
            # msdb may be unavailable or permissions may be insufficient —
            # this is a best-effort query; the caller handles the empty result.
            return []
