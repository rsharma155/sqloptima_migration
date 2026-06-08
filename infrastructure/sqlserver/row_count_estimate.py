"""
Module: infrastructure/sqlserver/row_count_estimate.py
Purpose: SQL Server table row counts — prefer sys.partitions (DMV) when
         VIEW DATABASE STATE is granted; fall back to COUNT(*) for least-privilege logins.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from typing import Any

from shared.kernel.sql_identifier import validate_sql_identifier
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

_PARTITION_ROW_COUNT_SQL = """
SELECT COALESCE(SUM(p.rows), 0) AS row_count
FROM sys.partitions p
INNER JOIN sys.objects o ON p.object_id = o.object_id
INNER JOIN sys.schemas s ON o.schema_id = s.schema_id
WHERE s.name = ? AND o.name = ? AND p.index_id IN (0, 1)
"""

# Per-connector cache: True → DMV works; False → skip DMV (use COUNT(*)).
_dmv_supported_by_connector: dict[int, bool] = {}


def _connector_key(connector: Any) -> int:
    return id(connector)


def reset_sqlserver_row_count_strategy_cache() -> None:
    """Clear cached DMV availability (for tests)."""
    _dmv_supported_by_connector.clear()


async def fetch_sqlserver_table_row_estimate(
    connector: Any,
    schema: str,
    table: str,
) -> int:
    """Return row count for a SQL Server table.

    Uses ``sys.partitions`` when ``VIEW DATABASE STATE`` is available (fast estimate).
    Falls back to ``COUNT(*)`` when the DMV is not permitted or fails, so DBAs can
    omit ``VIEW DATABASE STATE`` from least-privilege migration readers.
    """
    validate_sql_identifier(schema, "schema")
    validate_sql_identifier(table, "table")

    key = _connector_key(connector)
    dmv_allowed = _dmv_supported_by_connector.get(key, True)

    if dmv_allowed:
        count, dmv_ok = await _fetch_from_partitions(connector, schema, table)
        if dmv_ok:
            _dmv_supported_by_connector[key] = True
            return count
        _dmv_supported_by_connector[key] = False
        logger.info(
            "sqlserver_row_count_using_exact_count",
            schema=schema,
            table=table,
            reason="sys.partitions unavailable — falling back to COUNT(*)",
        )

    return await _fetch_exact_count(connector, schema, table)


async def _fetch_from_partitions(
    connector: Any,
    schema: str,
    table: str,
) -> tuple[int, bool]:
    """Return (row_count, dmv_succeeded)."""
    try:
        rows = await connector.execute(
            _PARTITION_ROW_COUNT_SQL,
            {"schema": schema, "table": table},
        )
        if rows and rows[0].get("row_count") is not None:
            return int(rows[0]["row_count"]), True
    except Exception as exc:
        logger.warning(
            "sqlserver_row_estimate_dmv_failed",
            schema=schema,
            table=table,
            error=str(exc),
        )
    return 0, False


async def _fetch_exact_count(connector: Any, schema: str, table: str) -> int:
    try:
        rows = await connector.execute(
            f"SELECT COUNT(*) AS cnt FROM [{schema}].[{table}]",
        )
        if rows and rows[0].get("cnt") is not None:
            return int(rows[0]["cnt"])
    except Exception as exc:
        logger.warning(
            "sqlserver_row_count_exact_failed",
            schema=schema,
            table=table,
            error=str(exc),
        )
    return 0
