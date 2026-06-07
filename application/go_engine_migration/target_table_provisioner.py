"""
Module: target_table_provisioner.py
Purpose: Create missing PostgreSQL target tables before Go engine data COPY.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from typing import Any

from domains.migration.go_type_mapping import map_sqlserver_to_postgres_ddl
from infrastructure.sqlserver.sqlserver_discovery import SqlServerMetadataDiscovery
from shared.kernel.database_object import Column, Table
from shared.kernel.ddl_identifier import quote_pg_ident
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

_PK_SQL = """
SELECT c.name AS column_name
FROM sys.key_constraints kc
JOIN sys.index_columns ic
  ON ic.object_id = kc.parent_object_id AND ic.index_id = kc.unique_index_id
JOIN sys.columns c
  ON c.object_id = ic.object_id AND c.column_id = ic.column_id
WHERE kc.type = 'PK'
  AND kc.parent_object_id = OBJECT_ID(?)
ORDER BY ic.key_ordinal
"""


def _column_def(col: Column) -> str:
    dt = col.data_type
    pg_type = map_sqlserver_to_postgres_ddl(
        dt.type_name,
        max_length=dt.max_length,
        precision=dt.precision,
        scale=dt.scale,
    )
    parts = [quote_pg_ident(col.column_name), pg_type]
    if not col.is_nullable:
        parts.append("NOT NULL")
    return " ".join(parts)


def build_create_table_ddl(
    table: Table,
    *,
    target_schema: str,
    pk_columns: list[str] | None = None,
) -> str:
    """Build ``CREATE TABLE IF NOT EXISTS`` for a discovered SQL Server table."""
    if not table.columns:
        raise ValueError(f"No columns discovered for {table.schema_name}.{table.object_name}")

    col_lines = [_column_def(col) for col in table.columns]
    if pk_columns:
        pk_list = ", ".join(quote_pg_ident(c) for c in pk_columns)
        col_lines.append(f"PRIMARY KEY ({pk_list})")

    qualified = f"{quote_pg_ident(target_schema)}.{quote_pg_ident(table.object_name)}"
    body = ",\n  ".join(col_lines)
    return f"CREATE TABLE IF NOT EXISTS {qualified} (\n  {body}\n);"


async def _target_table_exists(target_connector: Any, target_schema: str, table_name: str) -> bool:
    rows = await target_connector.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = $1
              AND c.relname = $2
              AND c.relkind = 'r'
        ) AS exists
        """,
        target_schema,
        table_name,
    )
    return bool(rows and rows[0].get("exists"))


async def _fetch_pk_columns(
    source_connector: Any,
    source_schema: str,
    table_name: str,
) -> list[str]:
    full_name = f"{source_schema}.{table_name}"
    rows = await source_connector.execute(_PK_SQL, {"full_name": full_name})
    return [str(r["column_name"]) for r in rows]


async def provision_target_tables(
    source_connector: Any,
    target_connector: Any,
    *,
    database: str,
    source_schema: str,
    target_schema: str,
    table_names: list[str],
) -> list[str]:
    """Create any missing target tables. Returns names of tables that were created."""
    if target_schema != "public":
        await target_connector.execute(
            f"CREATE SCHEMA IF NOT EXISTS {quote_pg_ident(target_schema)}"
        )

    discovery = SqlServerMetadataDiscovery(source_connector)
    discovered = await discovery.discover_tables(database, source_schema)
    by_name = {t.object_name.lower(): t for t in discovered}

    created: list[str] = []
    for table_name in table_names:
        meta = by_name.get(table_name.lower())
        if not meta:
            raise ValueError(
                f"Source table {source_schema}.{table_name} not found — "
                "cannot provision PostgreSQL target"
            )

        if await _target_table_exists(target_connector, target_schema, table_name):
            logger.info(
                "target_table_exists",
                target_schema=target_schema,
                table=table_name,
            )
            continue

        pk_columns = await _fetch_pk_columns(source_connector, source_schema, table_name)
        ddl = build_create_table_ddl(
            meta,
            target_schema=target_schema,
            pk_columns=pk_columns or None,
        )
        await target_connector.execute(ddl)
        created.append(table_name)
        logger.info(
            "target_table_provisioned",
            source=f"{source_schema}.{table_name}",
            target=f"{target_schema}.{table_name}",
        )

    return created
