"""
Module: go_migration_column_resolver.py
Purpose: Resolve wildcard column lists before Go job dispatch.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from typing import Any

from shared.kernel.database_object import Column


_LIST_COLUMNS_SQL = """
SELECT c.name AS column_name
FROM sys.columns c
INNER JOIN sys.tables t ON t.object_id = c.object_id
INNER JOIN sys.schemas s ON s.schema_id = t.schema_id
WHERE s.name = ? AND t.name = ?
ORDER BY c.column_id
"""


def format_sqlserver_column_type(col: Column) -> str:
    """Format a catalog column type for Go ``MapSQLServerType`` (includes (max) suffix)."""
    dt = col.data_type
    name = (dt.type_name or "varchar").lower()
    if name in ("varchar", "nvarchar", "char", "nchar", "binary", "varbinary"):
        if dt.max_length == -1:
            return f"{name}(max)"
        return name
    if name in ("decimal", "numeric") and dt.precision is not None:
        return f"{name}({dt.precision},{dt.scale or 0})"
    return name


async def resolve_source_table_column_types(
    connector: Any,
    database: str,
    schema: str,
    table_names: list[str],
) -> dict[str, dict[str, str]]:
    """Load SQL Server column types so Go binary COPY uses matching encodings."""
    from infrastructure.sqlserver.sqlserver_discovery import SqlServerMetadataDiscovery

    discovery = SqlServerMetadataDiscovery(connector)
    discovered = await discovery.discover_tables(database, schema)
    by_name = {t.object_name.lower(): t for t in discovered}

    result: dict[str, dict[str, str]] = {}
    for table in table_names:
        meta = by_name.get(table.lower())
        if not meta or not meta.columns:
            result[table] = {}
            continue
        result[table] = {
            col.column_name: format_sqlserver_column_type(col)
            for col in meta.columns
            if col.data_type and col.data_type.type_name
        }
    return result


async def resolve_source_table_columns(
    connector: Any,
    schema: str,
    table: str,
    columns: list[str],
    *,
    database: str | None = None,
) -> list[str]:
    """Expand ``["*"]`` to concrete SQL Server column names via catalog metadata.

    Never uses ``SELECT *`` — pyodbc cannot read ``sql_variant``, ``hierarchyid``,
    ``geography``, or ``geometry`` without an explicit cast.
    """
    if columns and columns != ["*"]:
        return columns

    if database:
        from domains.migration.column_type_override import discover_table_column_types

        catalog_cols = await discover_table_column_types(
            connector, database, schema, table,
        )
        if catalog_cols:
            return [name for name, _ in catalog_cols]

    rows = await connector.execute(
        _LIST_COLUMNS_SQL,
        {"schema": schema, "table": table},
    )
    if rows:
        return [str(r["column_name"]) for r in rows]

    raise ValueError(
        f"Could not resolve columns for {schema}.{table} — "
        "table not found in catalog or has no columns"
    )
