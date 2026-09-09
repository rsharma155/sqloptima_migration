"""
Module: inventory.py
Purpose: Load table/constraint inventories for Transfer preflight.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from typing import Any

from domains.transfer.connection_engine import DatabaseEngine
from domains.transfer.preflight import ColumnInventory, ObjectInventory, TableInventory

_PG_FKS = """
SELECT con.conname AS name, pg_get_constraintdef(con.oid) AS definition
FROM pg_constraint con
JOIN pg_class t ON con.conrelid = t.oid
JOIN pg_namespace n ON t.relnamespace = n.oid
WHERE con.contype = 'f'
  AND n.nspname = $1
  AND t.relname = $2
"""

_PG_CHECKS = """
SELECT con.conname AS name, pg_get_constraintdef(con.oid) AS definition
FROM pg_constraint con
JOIN pg_class t ON con.conrelid = t.oid
JOIN pg_namespace n ON t.relnamespace = n.oid
WHERE con.contype = 'c'
  AND n.nspname = $1
  AND t.relname = $2
"""

_PG_TRIGGERS = """
SELECT t.tgname AS name, pg_get_triggerdef(t.oid) AS definition
FROM pg_trigger t
JOIN pg_class c ON t.tgrelid = c.oid
JOIN pg_namespace n ON c.relnamespace = n.oid
WHERE n.nspname = $1
  AND c.relname = $2
  AND NOT t.tgisinternal
"""

_MSSQL_CHECKS = """
SELECT cc.name, cc.definition
FROM sys.check_constraints cc
INNER JOIN sys.tables t ON cc.parent_object_id = t.object_id
INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
WHERE s.name = ? AND t.name = ?
"""

_MSSQL_TRIGGERS = """
SELECT tr.name, m.definition
FROM sys.triggers tr
INNER JOIN sys.tables t ON tr.parent_id = t.object_id
INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
LEFT JOIN sys.sql_modules m ON tr.object_id = m.object_id
WHERE s.name = ? AND t.name = ?
"""


async def load_table_inventory(
    connector: Any,
    engine: DatabaseEngine,
    database: str,
    schema: str,
    table: str,
) -> TableInventory:
    if engine is DatabaseEngine.POSTGRES:
        from infrastructure.postgres.postgres_discovery import PostgresMetadataDiscovery

        discovery = PostgresMetadataDiscovery(connector)
        return await _from_discovery(discovery, connector, engine, database, schema, table)

    from infrastructure.sqlserver.sqlserver_discovery import SqlServerMetadataDiscovery

    discovery = SqlServerMetadataDiscovery(connector)
    return await _from_discovery(discovery, connector, engine, database, schema, table)


async def list_schema_tables(
    connector: Any,
    engine: DatabaseEngine,
    database: str,
    schema: str,
) -> list[dict[str, Any]]:
    if engine is DatabaseEngine.POSTGRES:
        from infrastructure.postgres.postgres_discovery import PostgresMetadataDiscovery

        discovery = PostgresMetadataDiscovery(connector)
    else:
        from infrastructure.sqlserver.sqlserver_discovery import SqlServerMetadataDiscovery

        discovery = SqlServerMetadataDiscovery(connector)
    tables = await discovery.discover_tables(database, schema)
    return [
        {
            "schema": t.schema_name,
            "table": t.object_name,
            "row_count_estimate": int(getattr(t, "row_count_estimate", 0) or 0),
            "column_count": len(getattr(t, "columns", []) or []),
        }
        for t in tables
    ]


async def list_schemas(connector: Any, engine: DatabaseEngine, database: str) -> list[str]:
    if engine is DatabaseEngine.POSTGRES:
        from infrastructure.postgres.postgres_discovery import PostgresMetadataDiscovery

        discovery = PostgresMetadataDiscovery(connector)
    else:
        from infrastructure.sqlserver.sqlserver_discovery import SqlServerMetadataDiscovery

        discovery = SqlServerMetadataDiscovery(connector)
    schemas = await discovery.discover_schemas(database)
    return [s.schema_name or s.object_name for s in schemas]


async def _from_discovery(
    discovery: Any,
    connector: Any,
    engine: DatabaseEngine,
    database: str,
    schema: str,
    table: str,
) -> TableInventory:
    tables = await discovery.discover_tables(database, schema)
    found = next((t for t in tables if t.object_name.lower() == table.lower()), None)
    if found is None:
        return TableInventory(schema=schema, table=table, exists=False)

    columns = [
        ColumnInventory(
            name=c.column_name,
            type_name=c.data_type.type_name if c.data_type else "",
            nullable=bool(c.is_nullable),
            is_identity=bool(c.is_identity),
        )
        for c in (found.columns or [])
    ]
    indexes_raw = await discovery.discover_indexes(database, schema, table)
    fks_raw = await discovery.discover_foreign_keys(database, schema, table)
    checks, triggers = await _load_checks_and_triggers(connector, engine, schema, table)
    fk_defs = await _load_fk_definitions(connector, engine, schema, table)

    constraints: list[ObjectInventory] = []
    indexes: list[ObjectInventory] = []
    for idx in indexes_raw:
        props = idx.properties or {}
        item = ObjectInventory(
            object_id=idx.object_name,
            kind="primary_key" if props.get("is_primary_key") else "index",
            extra={
                "is_primary_key": bool(props.get("is_primary_key")),
                "is_unique": bool(props.get("is_unique")),
                "index_type": props.get("index_type"),
                "definition": props.get("index_definition") or "",
            },
        )
        if props.get("is_primary_key"):
            constraints.append(item)
        else:
            indexes.append(item)

    foreign_keys = []
    for fk in fks_raw:
        props = fk.properties or {}
        referenced = props.get("referenced_table") or props.get("referenced") or ""
        foreign_keys.append(
            ObjectInventory(
                object_id=fk.object_name,
                kind="foreign_key",
                extra={
                    "referenced": referenced,
                    "referenced_table": referenced,
                    "direction": "outgoing",
                    "definition": fk_defs.get(fk.object_name) or props.get("definition") or "",
                },
            )
        )

    return TableInventory(
        schema=schema,
        table=found.object_name,
        exists=True,
        row_count=int(getattr(found, "row_count_estimate", 0) or 0),
        columns=columns,
        constraints=constraints + checks,
        indexes=indexes,
        foreign_keys=foreign_keys,
        triggers=triggers,
    )


async def _load_checks_and_triggers(
    connector: Any,
    engine: DatabaseEngine,
    schema: str,
    table: str,
) -> tuple[list[ObjectInventory], list[ObjectInventory]]:
    try:
        if engine is DatabaseEngine.POSTGRES:
            check_rows = await connector.execute(_PG_CHECKS, schema, table)
            trigger_rows = await connector.execute(_PG_TRIGGERS, schema, table)
        else:
            check_rows = await connector.execute(_MSSQL_CHECKS, schema, table)
            trigger_rows = await connector.execute(_MSSQL_TRIGGERS, schema, table)
    except Exception:
        return [], []

    checks = [
        ObjectInventory(
            object_id=str(r.get("name") or r.get("conname")),
            kind="check",
            extra={"definition": str(r.get("definition") or "")},
        )
        for r in check_rows
        if r.get("name") or r.get("conname")
    ]
    triggers = [
        ObjectInventory(
            object_id=str(r.get("name") or r.get("tgname")),
            kind="trigger",
            extra={"timing": "insert", "definition": str(r.get("definition") or "")},
        )
        for r in trigger_rows
        if r.get("name") or r.get("tgname")
    ]
    return checks, triggers


async def _load_fk_definitions(
    connector: Any,
    engine: DatabaseEngine,
    schema: str,
    table: str,
) -> dict[str, str]:
    if engine is not DatabaseEngine.POSTGRES:
        return {}
    try:
        rows = await connector.execute(_PG_FKS, schema, table)
    except Exception:
        return {}
    return {
        str(r.get("name") or r.get("conname")): str(r.get("definition") or "")
        for r in rows
        if r.get("name") or r.get("conname")
    }
