"""
Module: domains/discovery/index_discovery.py
Purpose: Discovers indexes and sequences from SQL Server sys.* catalog views.
         Results feed the ComparisonEngine so missing indexes are surfaced before cutover.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


@dataclass
class DiscoveredIndex:
    schema_name: str
    table_name: str
    index_name: str
    is_unique: bool
    is_primary_key: bool
    is_clustered: bool
    key_columns: list[str] = field(default_factory=list)
    include_columns: list[str] = field(default_factory=list)
    filter_definition: str | None = None


@dataclass
class DiscoveredSequence:
    schema_name: str
    sequence_name: str
    data_type: str
    start_value: int
    increment: int
    min_value: int | None
    max_value: int | None
    cycle: bool


# ---------------------------------------------------------------------------
# Discoverers
# ---------------------------------------------------------------------------


class IndexDiscovery:
    """Fix 5.1: discovers all user indexes from sys.indexes + sys.index_columns.

    Only non-system indexes are returned (is_ms_shipped = 0, type > 0).
    Primary key indexes are included so the comparison layer can verify PK parity.
    """

    _SQL = """
        SELECT
            s.name                              AS schema_name,
            t.name                              AS table_name,
            i.name                              AS index_name,
            CAST(i.is_unique AS BIT)            AS is_unique,
            CAST(i.is_primary_key AS BIT)       AS is_primary_key,
            CAST(CASE WHEN i.type = 1 THEN 1 ELSE 0 END AS BIT) AS is_clustered,
            c.name                              AS column_name,
            CAST(ic.is_included_column AS BIT)  AS is_included,
            ic.key_ordinal
        FROM sys.indexes            i
        JOIN sys.tables             t  ON t.object_id  = i.object_id
        JOIN sys.schemas            s  ON s.schema_id  = t.schema_id
        JOIN sys.index_columns      ic ON ic.object_id = i.object_id
                                      AND ic.index_id  = i.index_id
        JOIN sys.columns            c  ON c.object_id  = ic.object_id
                                      AND c.column_id  = ic.column_id
        WHERE t.is_ms_shipped = 0
          AND i.type > 0
          AND s.name = ?
        ORDER BY s.name, t.name, i.name, ic.key_ordinal
    """

    async def discover(self, connector: Any, schema: str) -> list[DiscoveredIndex]:
        rows = await connector.execute(self._SQL, schema)

        index_map: dict[tuple[str, str, str], DiscoveredIndex] = {}
        for row in rows:
            key = (row["schema_name"], row["table_name"], row["index_name"])
            if key not in index_map:
                index_map[key] = DiscoveredIndex(
                    schema_name=row["schema_name"],
                    table_name=row["table_name"],
                    index_name=row["index_name"],
                    is_unique=bool(row["is_unique"]),
                    is_primary_key=bool(row["is_primary_key"]),
                    is_clustered=bool(row["is_clustered"]),
                )
            idx = index_map[key]
            if row["is_included"]:
                idx.include_columns.append(row["column_name"])
            else:
                idx.key_columns.append(row["column_name"])

        indexes = list(index_map.values())
        logger.info("index_discovery_complete", schema=schema, count=len(indexes))
        return indexes


class SequenceDiscovery:
    """Fix 5.1: discovers sequences from sys.sequences so they can be recreated on PostgreSQL."""

    _SQL = """
        SELECT
            s.name          AS schema_name,
            seq.name        AS sequence_name,
            tp.name         AS data_type,
            seq.start_value,
            seq.increment,
            seq.minimum_value,
            seq.maximum_value,
            CAST(seq.is_cycling AS BIT) AS cycle
        FROM sys.sequences  seq
        JOIN sys.schemas    s   ON s.schema_id = seq.schema_id
        JOIN sys.types      tp  ON tp.user_type_id = seq.user_type_id
        WHERE s.name = ?
        ORDER BY s.name, seq.name
    """

    async def discover(self, connector: Any, schema: str) -> list[DiscoveredSequence]:
        rows = await connector.execute(self._SQL, schema)
        sequences = [
            DiscoveredSequence(
                schema_name=row["schema_name"],
                sequence_name=row["sequence_name"],
                data_type=row["data_type"],
                start_value=int(row["start_value"]),
                increment=int(row["increment"]),
                min_value=int(row["minimum_value"]) if row.get("minimum_value") is not None else None,
                max_value=int(row["maximum_value"]) if row.get("maximum_value") is not None else None,
                cycle=bool(row["cycle"]),
            )
            for row in rows
        ]
        logger.info("sequence_discovery_complete", schema=schema, count=len(sequences))
        return sequences
