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

# Minimal DDL for bulk COPY — identity, defaults, secondary indexes, FK, CHECK,
# and triggers are deferred to post-migration finalize.
MIGRATION_LOAD_DDL_POLICY = "minimal_load"

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


def _column_def(
    col: Column,
    *,
    pg_type_override: str | None = None,
) -> str:
    """Build a plain column definition for bulk load (no identity or defaults)."""
    dt = col.data_type
    pg_type = pg_type_override or map_sqlserver_to_postgres_ddl(
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
    column_pg_types: dict[str, str] | None = None,
) -> str:
    """Build ``CREATE TABLE IF NOT EXISTS`` for bulk data migration.

    Only columns and primary key are included. Identity columns remain plain
    integer types so COPY can insert explicit source values. Defaults, secondary
    indexes, foreign keys, check constraints, and triggers are applied later by
    :mod:`application.go_engine_migration.post_migration_finalizer`.
    """
    if not table.columns:
        raise ValueError(f"No columns discovered for {table.schema_name}.{table.object_name}")

    col_lines = [
        _column_def(
            col,
            pg_type_override=(column_pg_types or {}).get(col.column_name),
        )
        for col in table.columns
    ]
    if pk_columns:
        pk_list = ", ".join(quote_pg_ident(c) for c in pk_columns)
        col_lines.append(f"PRIMARY KEY ({pk_list})")

    qualified = f"{quote_pg_ident(target_schema)}.{quote_pg_ident(table.object_name)}"
    body = ",\n  ".join(col_lines)
    return f"CREATE TABLE IF NOT EXISTS {qualified} (\n  {body}\n);"


async def target_table_exists(target_connector: Any, target_schema: str, table_name: str) -> bool:
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


# Backward-compatible alias for internal callers
_target_table_exists = target_table_exists


async def get_target_table_row_count(
    target_connector: Any,
    target_schema: str,
    table_name: str,
) -> int:
    if not await target_table_exists(target_connector, target_schema, table_name):
        return 0
    qualified = f"{quote_pg_ident(target_schema)}.{quote_pg_ident(table_name)}"
    try:
        rows = await target_connector.execute(f"SELECT COUNT(*) AS cnt FROM {qualified}")
        return int(rows[0]["cnt"]) if rows else 0
    except Exception as exc:
        logger.warning(
            "target_row_count_failed",
            schema=target_schema,
            table=table_name,
            error=str(exc),
        )
        return -1


async def drop_target_table(
    target_connector: Any,
    target_schema: str,
    table_name: str,
) -> None:
    qualified = f"{quote_pg_ident(target_schema)}.{quote_pg_ident(table_name)}"
    await target_connector.execute(f"DROP TABLE IF EXISTS {qualified} CASCADE")


async def truncate_target_table(
    target_connector: Any,
    target_schema: str,
    table_name: str,
) -> None:
    qualified = f"{quote_pg_ident(target_schema)}.{quote_pg_ident(table_name)}"
    await target_connector.execute(f"TRUNCATE TABLE {qualified}")


async def _fetch_pk_columns(
    source_connector: Any,
    source_schema: str,
    table_name: str,
) -> list[str]:
    full_name = f"{source_schema}.{table_name}"
    rows = await source_connector.execute(_PK_SQL, {"full_name": full_name})
    return [str(r["column_name"]) for r in rows]


async def _create_target_table(
    source_connector: Any,
    target_connector: Any,
    *,
    database: str,
    source_schema: str,
    target_schema: str,
    table_name: str,
    meta: Table,
    column_pg_types: dict[str, str] | None = None,
) -> None:
    pk_columns = await _fetch_pk_columns(source_connector, source_schema, table_name)
    ddl = build_create_table_ddl(
        meta,
        target_schema=target_schema,
        pk_columns=pk_columns or None,
        column_pg_types=column_pg_types,
    )
    await target_connector.execute(ddl)
    logger.info(
        "target_table_provisioned",
        source=f"{source_schema}.{table_name}",
        target=f"{target_schema}.{table_name}",
    )


async def ensure_target_schema_exists(target_connector: Any, target_schema: str) -> None:
    """Create the PostgreSQL schema when it is not ``public`` (which always exists)."""
    if target_schema.lower() == "public":
        return
    await target_connector.execute(
        f"CREATE SCHEMA IF NOT EXISTS {quote_pg_ident(target_schema)}"
    )


async def provision_target_tables(
    source_connector: Any,
    target_connector: Any,
    *,
    database: str,
    source_schema: str,
    target_schema: str,
    table_names: list[str],
    table_policies: dict[str, str] | None = None,
    column_type_overrides_by_table: dict[str, dict[str, str]] | None = None,
) -> list[str]:
    """Create or prepare target tables. Returns names of newly created tables."""
    from application.go_engine_migration.target_table_preflight import TargetTablePolicy

    await ensure_target_schema_exists(target_connector, target_schema)

    discovery = SqlServerMetadataDiscovery(source_connector)
    discovered = await discovery.discover_tables(database, source_schema)
    by_name = {t.object_name.lower(): t for t in discovered}

    policies = table_policies or {}
    created: list[str] = []

    for table_name in table_names:
        meta = by_name.get(table_name.lower())
        if not meta:
            raise ValueError(
                f"Source table {source_schema}.{table_name} not found — "
                "cannot provision PostgreSQL target"
            )

        policy = policies.get(table_name, TargetTablePolicy.USE_EXISTING.value)
        exists = await target_table_exists(target_connector, target_schema, table_name)

        if not exists:
            table_pg_types = (column_type_overrides_by_table or {}).get(table_name)
            await _create_target_table(
                source_connector,
                target_connector,
                database=database,
                source_schema=source_schema,
                target_schema=target_schema,
                table_name=table_name,
                meta=meta,
                column_pg_types=table_pg_types,
            )
            created.append(table_name)
            continue

        row_count = await get_target_table_row_count(
            target_connector, target_schema, table_name,
        )

        if policy == TargetTablePolicy.USE_EXISTING.value:
            logger.info(
                "target_table_exists",
                target_schema=target_schema,
                table=table_name,
                row_count=row_count,
            )
            continue

        if policy == TargetTablePolicy.DROP_EMPTY_RECREATE.value:
            if row_count > 0:
                raise ValueError(
                    f"Target table {target_schema}.{table_name} has {row_count:,} row(s) "
                    "— cannot drop_empty_recreate without truncating first."
                )
            await drop_target_table(target_connector, target_schema, table_name)
            await _create_target_table(
                source_connector,
                target_connector,
                database=database,
                source_schema=source_schema,
                target_schema=target_schema,
                table_name=table_name,
                meta=meta,
            )
            created.append(table_name)
            logger.info(
                "target_table_recreated_empty",
                target_schema=target_schema,
                table=table_name,
            )
            continue

        if policy == TargetTablePolicy.TRUNCATE_RELOAD.value:
            await truncate_target_table(target_connector, target_schema, table_name)
            logger.info(
                "target_table_truncated",
                target_schema=target_schema,
                table=table_name,
                previous_rows=row_count,
            )
            continue

        raise ValueError(f"Unsupported target table policy {policy!r} for {table_name}")

    return created
