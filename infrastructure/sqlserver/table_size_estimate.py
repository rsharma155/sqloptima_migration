"""
Module: table_size_estimate.py
Purpose: Approximate SQL Server table size in megabytes for migration throttling.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from typing import Any

from shared.kernel.sql_identifier import validate_sql_identifier

_TABLE_SIZE_MB_SQL = """
SELECT COALESCE(SUM(a.total_pages) * 8.0 / 1024.0, 0) AS size_mb
FROM sys.tables t
INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
INNER JOIN sys.indexes i ON t.object_id = i.object_id
INNER JOIN sys.partitions p ON i.object_id = p.object_id AND i.index_id = p.index_id
INNER JOIN sys.allocation_units a ON p.partition_id = a.container_id
WHERE s.name = ? AND t.name = ? AND i.index_id IN (0, 1)
"""


async def fetch_sqlserver_table_size_mb(
    connector: Any,
    schema: str,
    table: str,
) -> float:
    """Return approximate on-disk table size in megabytes (heap + clustered index)."""
    validate_sql_identifier(schema, "schema")
    validate_sql_identifier(table, "table")
    try:
        rows = await connector.execute(
            _TABLE_SIZE_MB_SQL,
            {"schema": schema, "table": table},
        )
        if not rows:
            return 0.0
        return float(rows[0].get("size_mb") or 0.0)
    except Exception:
        return 0.0
