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
) -> list[str]:
    """Expand ``["*"]`` to concrete SQL Server column names."""
    if columns and columns != ["*"]:
        return columns
    sample = await connector.execute(f"SELECT TOP 1 * FROM [{schema}].[{table}]")
    if sample:
        return list(sample[0].keys())
    raise ValueError(f"Could not resolve columns for {schema}.{table} — table may be empty")
