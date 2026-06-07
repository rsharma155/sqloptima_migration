"""
Module: domains/discovery/computed_column_discovery.py
Purpose: Discovers computed columns from SQL Server sys.computed_columns so their
         expressions can be analysed and recreated as PostgreSQL GENERATED ALWAYS AS
         expressions or replaced with materialised columns.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


@dataclass
class ComputedColumnInfo:
    schema_name: str
    table_name: str
    column_name: str
    definition: str
    is_persisted: bool
    uses_ansi_padding: bool


class ComputedColumnDiscovery:
    """Fix 5.2: discovers computed columns per schema.

    Returns the T-SQL definition so the transpilation layer can attempt
    automatic conversion to a PostgreSQL GENERATED ALWAYS AS expression.
    Non-convertible expressions are surfaced as assessment blockers.
    """

    _SQL = """
        SELECT
            s.name                              AS schema_name,
            t.name                              AS table_name,
            c.name                              AS column_name,
            cc.definition                       AS definition,
            CAST(cc.is_persisted AS BIT)        AS is_persisted,
            CAST(c.uses_ansi_padding AS BIT)    AS uses_ansi_padding
        FROM sys.computed_columns   cc
        JOIN sys.columns            c  ON c.object_id  = cc.object_id
                                      AND c.column_id  = cc.column_id
        JOIN sys.tables             t  ON t.object_id  = cc.object_id
        JOIN sys.schemas            s  ON s.schema_id  = t.schema_id
        WHERE t.is_ms_shipped = 0
          AND s.name = ?
        ORDER BY s.name, t.name, c.column_id
    """

    async def discover(self, connector: Any, schema: str) -> list[ComputedColumnInfo]:
        rows = await connector.execute(self._SQL, schema)
        result = [
            ComputedColumnInfo(
                schema_name=row["schema_name"],
                table_name=row["table_name"],
                column_name=row["column_name"],
                definition=row["definition"] or "",
                is_persisted=bool(row["is_persisted"]),
                uses_ansi_padding=bool(row["uses_ansi_padding"]),
            )
            for row in rows
        ]
        logger.info("computed_column_discovery_complete", schema=schema, count=len(result))
        return result
