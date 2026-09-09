"""
Module: postgres_discovery.py
Purpose: PostgreSQL metadata discovery using information_schema and pg_catalog
Author: Migration Platform Team
Created: 2026-05-22
Domain: Infrastructure
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from typing import Any

from infrastructure.postgres.postgres_connector import PostgresConnector
from shared.contracts.base_connector import MetadataDiscoveryPort
from shared.kernel.database_object import (
    Column,
    DatabaseObject,
    DatabaseObjectType,
    DataType,
    Table,
)

QUERY_SCHEMAS = """
SELECT schema_name
FROM information_schema.schemata
WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
ORDER BY schema_name
"""

QUERY_TABLES = """
SELECT
    t.table_schema AS schema_name,
    t.table_name,
    (SELECT COUNT(*) FROM information_schema.columns c
     WHERE c.table_schema = t.table_schema AND c.table_name = t.table_name) AS column_count,
    COALESCE(pc.reltuples::bigint, 0) AS row_count_estimate
FROM information_schema.tables t
LEFT JOIN pg_namespace pn ON pn.nspname = t.table_schema
LEFT JOIN pg_class pc
  ON pc.relnamespace = pn.oid
 AND pc.relname = t.table_name
 AND pc.relkind = 'r'
WHERE t.table_type = 'BASE TABLE'
  AND t.table_schema = $1
ORDER BY t.table_name
"""

QUERY_COLUMNS = """
SELECT
    c.column_name,
    c.ordinal_position,
    c.data_type,
    c.character_maximum_length,
    c.numeric_precision,
    c.numeric_scale,
    c.is_nullable,
    c.column_default,
    CASE WHEN c.is_identity = 'YES' THEN true ELSE false END AS is_identity,
    pgd.description AS column_comment
FROM information_schema.columns c
LEFT JOIN pg_catalog.pg_statio_all_tables st ON st.schemaname = c.table_schema AND st.relname = c.table_name
LEFT JOIN pg_catalog.pg_description pgd ON pgd.objoid = st.relid AND pgd.objsubid = c.ordinal_position
WHERE c.table_schema = $1 AND c.table_name = $2
ORDER BY c.ordinal_position
"""

QUERY_COLUMNS_BATCH = """
SELECT
    c.table_name,
    c.column_name,
    c.ordinal_position,
    c.data_type,
    c.character_maximum_length,
    c.numeric_precision,
    c.numeric_scale,
    c.is_nullable,
    c.column_default,
    CASE WHEN c.is_identity = 'YES' THEN true ELSE false END AS is_identity,
    pgd.description AS column_comment
FROM information_schema.columns c
LEFT JOIN pg_catalog.pg_statio_all_tables st ON st.schemaname = c.table_schema AND st.relname = c.table_name
LEFT JOIN pg_catalog.pg_description pgd ON pgd.objoid = st.relid AND pgd.objsubid = c.ordinal_position
WHERE c.table_schema = $1
ORDER BY c.table_name, c.ordinal_position
"""

QUERY_VIEWS = """
SELECT
    table_schema AS schema_name,
    table_name AS view_name,
    view_definition AS definition
FROM information_schema.views
WHERE table_schema = $1
ORDER BY table_name
"""

QUERY_PROCEDURES = """
SELECT
    n.nspname AS schema_name,
    p.proname AS procedure_name,
    pg_get_functiondef(p.oid) AS definition
FROM pg_proc p
JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE n.nspname = $1
  AND p.prokind = 'p'
ORDER BY p.proname
"""

QUERY_FUNCTIONS = """
SELECT
    n.nspname AS schema_name,
    p.proname AS function_name,
    pg_get_functiondef(p.oid) AS definition
FROM pg_proc p
JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE n.nspname = $1
  AND p.prokind = 'f'
ORDER BY p.proname
"""

QUERY_INDEXES = """
SELECT
    idx.relname AS index_name,
    a.amname AS index_type,
    i.indisunique AS is_unique,
    i.indisprimary AS is_primary_key,
    pg_get_indexdef(i.indexrelid) AS index_definition,
    string_agg(att.attname, ',' ORDER BY k.ord) AS column_names
FROM pg_index i
JOIN pg_class t ON i.indrelid = t.oid
JOIN pg_class idx ON i.indexrelid = idx.oid
JOIN pg_am a ON idx.relam = a.oid
LEFT JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord) ON true
LEFT JOIN pg_attribute att
    ON att.attrelid = t.oid AND att.attnum = k.attnum AND k.attnum > 0
WHERE t.relname = $1
  AND t.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = $2)
GROUP BY idx.relname, a.amname, i.indisunique, i.indisprimary, i.indexrelid
ORDER BY idx.relname
"""

QUERY_FOREIGN_KEYS = """
SELECT
    con.conname AS fk_name,
    t.relname AS parent_table,
    unnest(con.conkey) AS parent_column_attnum,
    ft.relname AS referenced_table,
    unnest(con.confkey) AS referenced_column_attnum
FROM pg_constraint con
JOIN pg_class t ON con.conrelid = t.oid
JOIN pg_class ft ON con.confrelid = ft.oid
WHERE con.contype = 'f'
  AND t.relname = $1
  AND t.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = $2)
"""

QUERY_TRIGGERS = """
SELECT
    n.nspname AS schema_name,
    t.tgrelid::regclass::text AS parent_table,
    t.tgname AS trigger_name,
    pg_get_triggerdef(t.oid) AS definition
FROM pg_trigger t
JOIN pg_class c ON t.tgrelid = c.oid
JOIN pg_namespace n ON c.relnamespace = n.oid
WHERE n.nspname = $1
  AND NOT t.tgisinternal
ORDER BY t.tgname
"""


class PostgresMetadataDiscovery(MetadataDiscoveryPort):
    """PostgreSQL metadata discovery implementation using pg_catalog."""

    def __init__(self, connector: PostgresConnector):
        self._connector = connector

    async def discover_databases(self) -> list[DatabaseObject]:
        results = await self._connector.execute("SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname")
        return [
            DatabaseObject(
                object_type=DatabaseObjectType.DATABASE,
                database_name=r["datname"],
                schema_name="",
                object_name=r["datname"],
            )
            for r in results
        ]

    async def discover_schemas(self, database: str) -> list[DatabaseObject]:
        results = await self._connector.execute(QUERY_SCHEMAS)
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
        results = await self._connector.execute(QUERY_TABLES, schema)
        if not results:
            return []

        table_names = [r["table_name"] for r in results]
        table_map = {r["table_name"]: r for r in results}

        col_results = await self._connector.execute(QUERY_COLUMNS_BATCH, schema)

        columns_by_table: dict[str, list[Column]] = {}
        for cr in col_results:
            tbl = cr["table_name"]
            if tbl not in columns_by_table:
                columns_by_table[tbl] = []
            dt = DataType(
                type_name=cr["data_type"],
                max_length=cr.get("character_maximum_length"),
                precision=cr.get("numeric_precision"),
                scale=cr.get("numeric_scale"),
                is_nullable=cr["is_nullable"] == "YES",
            )
            columns_by_table[tbl].append(
                Column(
                    table_id=None,
                    column_name=cr["column_name"],
                    ordinal_position=cr["ordinal_position"],
                    data_type=dt,
                    is_identity=bool(cr.get("is_identity", False)),
                    default_value=cr.get("column_default"),
                    is_nullable=cr["is_nullable"] == "YES",
                )
            )

        tables = []
        for name in table_names:
            r = table_map[name]
            columns = columns_by_table.get(name, [])
            tables.append(Table(
                database_name=database,
                schema_name=schema,
                object_name=r["table_name"],
                row_count_estimate=r.get("row_count_estimate", 0),
                columns=columns,
                index_count=len(columns),
            ))
        return tables

    async def discover_views(self, database: str, schema: str) -> list[DatabaseObject]:
        results = await self._connector.execute(QUERY_VIEWS, schema)
        return [
            DatabaseObject(
                object_type=DatabaseObjectType.VIEW,
                database_name=database,
                schema_name=r["schema_name"],
                object_name=r["view_name"],
                source_definition=r.get("definition", ""),
            )
            for r in results
        ]

    async def discover_procedures(self, database: str, schema: str) -> list[DatabaseObject]:
        results = await self._connector.execute(QUERY_PROCEDURES, schema)
        return [
            DatabaseObject(
                object_type=DatabaseObjectType.PROCEDURE,
                database_name=database,
                schema_name=r["schema_name"],
                object_name=r["procedure_name"],
                source_definition=r.get("definition", ""),
            )
            for r in results
        ]

    async def discover_functions(self, database: str, schema: str) -> list[DatabaseObject]:
        results = await self._connector.execute(QUERY_FUNCTIONS, schema)
        return [
            DatabaseObject(
                object_type=DatabaseObjectType.FUNCTION,
                database_name=database,
                schema_name=r["schema_name"],
                object_name=r["function_name"],
                source_definition=r.get("definition", ""),
            )
            for r in results
        ]

    async def discover_indexes(self, database: str, schema: str, table: str) -> list[DatabaseObject]:
        results = await self._connector.execute(QUERY_INDEXES, table, schema)
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
                    "columns": r.get("column_names") or "",
                    "index_definition": r.get("index_definition") or "",
                },
            )
            for r in results
        ]

    async def discover_foreign_keys(self, database: str, schema: str, table: str) -> list[DatabaseObject]:
        results = await self._connector.execute(QUERY_FOREIGN_KEYS, table, schema)
        fk_map: dict[str, dict] = {}
        for r in results:
            name = r["fk_name"]
            if name not in fk_map:
                fk_map[name] = {
                    "fk_name": name,
                    "parent_table": r["parent_table"],
                    "referenced_table": r["referenced_table"],
                }
        return [
            DatabaseObject(
                object_type=DatabaseObjectType.FOREIGN_KEY,
                database_name=database,
                schema_name=schema,
                object_name=name,
                properties=props,
            )
            for name, props in fk_map.items()
        ]

    async def discover_dependencies(self, database: str) -> list[dict[str, Any]]:
        results = await self._connector.execute("""
            SELECT
                dep.source_schema,
                dep.source_object,
                dep.target_schema,
                dep.target_object
            FROM (
                SELECT
                    n1.nspname AS source_schema,
                    c1.relname AS source_object,
                    n2.nspname AS target_schema,
                    c2.relname AS target_object
                FROM pg_depend d
                JOIN pg_class c1 ON d.objid = c1.oid
                JOIN pg_class c2 ON d.refobjid = c2.oid
                JOIN pg_namespace n1 ON c1.relnamespace = n1.oid
                JOIN pg_namespace n2 ON c2.relnamespace = n2.oid
                WHERE d.deptype = 'n'
            ) dep
        """)
        return [dict(r) for r in results]

    async def get_schema_ddl(self, database: str, schema: str) -> dict[str, str]:
        tables = await self.discover_tables(database, schema)
        views = await self.discover_views(database, schema)
        ddl_map: dict[str, str] = {}
        for t in tables:
            ddl_map[t.fully_qualified_name] = t.source_definition or ""
        for v in views:
            ddl_map[v.fully_qualified_name] = v.source_definition or ""
        return ddl_map
