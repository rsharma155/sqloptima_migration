"""
Module: schema_clone.py
Purpose: Load source metadata and build a Transfer schema-clone plan.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from typing import Any

from domains.migration.go_type_mapping import map_sqlserver_to_postgres_ddl
from domains.transfer.connection_engine import DatabaseEngine
from domains.transfer.schema_clone import (
    SchemaClonePlan,
    SchemaCloneStatement,
    build_add_check_tsql,
    build_add_foreign_key_tsql,
    build_create_index_tsql,
    build_create_schema_pg,
    build_create_schema_tsql,
    build_create_table_pg,
    build_create_table_tsql,
    split_tsql_batches,
    supports_table_clone,
    supports_tsql_object_clone,
)
from domains.transfer.transfer_models import TransferTableMapping
from domains.transfer.transfer_path import TransferPath
from shared.kernel.ddl_identifier import quote_pg_ident

_IDENTITY = """
SELECT
    OBJECT_SCHEMA_NAME(ic.object_id) AS schema_name,
    OBJECT_NAME(ic.object_id) AS table_name,
    c.name AS column_name,
    CAST(ic.seed_value AS BIGINT) AS seed_value,
    CAST(ic.increment_value AS BIGINT) AS increment_value
FROM sys.identity_columns ic
INNER JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
INNER JOIN sys.tables t ON t.object_id = ic.object_id
INNER JOIN sys.schemas s ON s.schema_id = t.schema_id
WHERE s.name = ?
"""

_COMPUTED_PERSISTED = """
SELECT
    OBJECT_SCHEMA_NAME(cc.object_id) AS schema_name,
    OBJECT_NAME(cc.object_id) AS table_name,
    c.name AS column_name,
    cc.is_persisted
FROM sys.computed_columns cc
INNER JOIN sys.columns c ON c.object_id = cc.object_id AND c.column_id = cc.column_id
INNER JOIN sys.tables t ON t.object_id = cc.object_id
INNER JOIN sys.schemas s ON s.schema_id = t.schema_id
WHERE s.name = ?
"""

_PK_NAMES = """
SELECT
    OBJECT_SCHEMA_NAME(kc.parent_object_id) AS schema_name,
    OBJECT_NAME(kc.parent_object_id) AS table_name,
    kc.name AS pk_name,
    c.name AS column_name,
    ic.key_ordinal
FROM sys.key_constraints kc
INNER JOIN sys.index_columns ic
    ON ic.object_id = kc.parent_object_id AND ic.index_id = kc.unique_index_id
INNER JOIN sys.columns c
    ON c.object_id = ic.object_id AND c.column_id = ic.column_id
WHERE kc.type = 'PK'
  AND OBJECT_SCHEMA_NAME(kc.parent_object_id) = ?
ORDER BY OBJECT_NAME(kc.parent_object_id), ic.key_ordinal
"""

_FK_FULL = """
SELECT
    fk.name AS fk_name,
    OBJECT_SCHEMA_NAME(fk.parent_object_id) AS schema_name,
    OBJECT_NAME(fk.parent_object_id) AS table_name,
    COL_NAME(fkc.parent_object_id, fkc.parent_column_id) AS parent_column,
    OBJECT_SCHEMA_NAME(fk.referenced_object_id) AS referenced_schema,
    OBJECT_NAME(fk.referenced_object_id) AS referenced_table,
    COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id) AS referenced_column,
    fk.delete_referential_action_desc AS delete_action,
    fk.update_referential_action_desc AS update_action,
    fkc.constraint_column_id
FROM sys.foreign_keys fk
INNER JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
WHERE OBJECT_SCHEMA_NAME(fk.parent_object_id) = ?
ORDER BY fk.name, fkc.constraint_column_id
"""


async def build_schema_clone_plan(
    *,
    path: TransferPath,
    source_connector: Any,
    source_engine: DatabaseEngine,
    source_database: str,
    tables: list[TransferTableMapping],
    missing_targets: set[str],
    create_if_missing: bool,
    clone_objects: bool,
) -> SchemaClonePlan:
    notes: list[str] = []
    _ = source_engine
    if not create_if_missing and not clone_objects:
        return SchemaClonePlan()
    if create_if_missing and not supports_table_clone(path):
        raise ValueError(
            f"Create-if-missing is not implemented for path {path.value}"
        )
    if clone_objects and not supports_tsql_object_clone(path):
        raise ValueError(
            "Clone schema/objects T-SQL as-is is only supported for SQL Server → SQL Server"
        )

    statements: list[SchemaCloneStatement] = []
    if path is TransferPath.MSSQL_TO_MSSQL:
        statements.extend(
            await _mssql_plan(
                source_connector,
                source_database,
                tables,
                missing_targets,
                create_if_missing=create_if_missing,
                clone_objects=clone_objects,
                notes=notes,
            )
        )
    elif path is TransferPath.PG_TO_PG:
        statements.extend(
            await _pg_table_plan(
                source_connector,
                source_database,
                tables,
                missing_targets,
                create_if_missing=create_if_missing,
                notes=notes,
            )
        )
    elif path is TransferPath.MSSQL_TO_PG:
        statements.extend(
            await _mssql_to_pg_table_plan(
                source_connector,
                source_database,
                tables,
                missing_targets,
                create_if_missing=create_if_missing,
                notes=notes,
            )
        )

    return SchemaClonePlan(
        create_if_missing=create_if_missing,
        clone_objects=clone_objects,
        statements=tuple(statements),
        notes=tuple(notes),
    )


async def _mssql_plan(
    connector: Any,
    database: str,
    tables: list[TransferTableMapping],
    missing_targets: set[str],
    *,
    create_if_missing: bool,
    clone_objects: bool,
    notes: list[str],
) -> list[SchemaCloneStatement]:
    from infrastructure.sqlserver.sqlserver_discovery import SqlServerMetadataDiscovery

    discovery = SqlServerMetadataDiscovery(connector)
    by_source_schema: dict[str, list[TransferTableMapping]] = {}
    for mapping in tables:
        by_source_schema.setdefault(mapping.source_schema, []).append(mapping)

    statements: list[SchemaCloneStatement] = []
    schemas_emitted: set[str] = set()

    for source_schema, mappings in by_source_schema.items():
        discovered = await discovery.discover_tables(database, source_schema)
        table_by_name = {t.object_name.lower(): t for t in discovered}
        identity = await _rows_by_table(connector, _IDENTITY, source_schema)
        persisted = await _rows_by_table(connector, _COMPUTED_PERSISTED, source_schema)
        pk_meta = await _pk_by_table(connector, source_schema)

        for mapping in mappings:
            src = table_by_name.get(mapping.source_table.lower())
            if src is None:
                continue
            target_key = mapping.target_key.lower()
            need_table = create_if_missing and target_key in missing_targets
            if need_table and mapping.target_schema not in schemas_emitted:
                statements.append(
                    SchemaCloneStatement(
                        phase="pre_copy",
                        kind="schema",
                        sql=build_create_schema_tsql(mapping.target_schema),
                        schema=mapping.target_schema,
                        name=mapping.target_schema,
                    )
                )
                schemas_emitted.add(mapping.target_schema)
            ident_cols = identity.get(mapping.source_table.lower(), [])
            persist_cols = persisted.get(mapping.source_table.lower(), [])
            ident_map = {r["column_name"].lower(): r for r in ident_cols}
            persist_map = {r["column_name"].lower(): r for r in persist_cols}
            pk = pk_meta.get(mapping.source_table.lower(), {"name": None, "columns": []})
            col_dicts = []
            for col in src.columns:
                extra = ident_map.get(col.column_name.lower(), {})
                persist = persist_map.get(col.column_name.lower(), {})
                col_dicts.append({
                    "name": col.column_name,
                    "type_name": col.data_type.type_name if col.data_type else "",
                    "max_length": col.data_type.max_length if col.data_type else None,
                    "precision": col.data_type.precision if col.data_type else None,
                    "scale": col.data_type.scale if col.data_type else None,
                    "nullable": col.is_nullable,
                    "is_identity": col.is_identity,
                    "is_computed": col.is_computed,
                    "computed_definition": col.computed_definition,
                    "is_persisted": bool(persist.get("is_persisted")),
                    "default_value": col.default_value,
                    "collation_name": col.collation_name,
                    "identity_seed": extra.get("seed_value") or 1,
                    "identity_increment": extra.get("increment_value") or 1,
                })
            if need_table:
                statements.append(
                    SchemaCloneStatement(
                        phase="pre_copy",
                        kind="table",
                        sql=build_create_table_tsql(
                            schema=mapping.target_schema,
                            table=mapping.target_table,
                            columns=col_dicts,
                            primary_key_columns=pk["columns"] or list(src.primary_key_columns or []),
                            primary_key_name=pk["name"],
                        ),
                        schema=mapping.target_schema,
                        name=mapping.target_table,
                    )
                )
            if clone_objects:
                statements.extend(
                    await _mssql_table_objects(connector, discovery, database, mapping)
                )

        if clone_objects:
            same_schema = all(m.source_schema == m.target_schema for m in mappings)
            if not same_schema:
                notes.append(
                    f"Views/procedures/functions in {source_schema} were skipped because "
                    "the target schema name differs; module T-SQL is cloned as-is."
                )
            else:
                statements.extend(
                    await _mssql_modules(discovery, database, source_schema)
                )

    return statements


async def _mssql_table_objects(
    connector: Any,
    discovery: Any,
    database: str,
    mapping: TransferTableMapping,
) -> list[SchemaCloneStatement]:
    statements: list[SchemaCloneStatement] = []
    indexes = await discovery.discover_indexes(database, mapping.source_schema, mapping.source_table)
    for idx in indexes:
        props = idx.properties or {}
        if props.get("is_primary_key"):
            continue
        cols = [c.strip() for c in str(props.get("columns") or "").split(",") if c.strip()]
        try:
            sql = build_create_index_tsql(
                schema=mapping.target_schema,
                table=mapping.target_table,
                index_name=idx.object_name,
                columns=cols,
                is_unique=bool(props.get("is_unique")),
                index_type=str(props.get("index_type") or "NONCLUSTERED"),
                filter_definition=props.get("filter_definition"),
            )
        except ValueError:
            continue
        statements.append(
            SchemaCloneStatement(
                phase="post_copy",
                kind="index",
                sql=sql,
                schema=mapping.target_schema,
                name=idx.object_name,
            )
        )

    checks = await connector.execute(
        """
        SELECT cc.name, cc.definition
        FROM sys.check_constraints cc
        INNER JOIN sys.tables t ON cc.parent_object_id = t.object_id
        INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ? AND t.name = ?
        """,
        mapping.source_schema,
        mapping.source_table,
    )
    for row in checks:
        try:
            sql = build_add_check_tsql(
                schema=mapping.target_schema,
                table=mapping.target_table,
                name=str(row["name"]),
                definition=str(row.get("definition") or ""),
            )
        except ValueError:
            continue
        statements.append(
            SchemaCloneStatement(
                phase="post_copy",
                kind="check",
                sql=sql,
                schema=mapping.target_schema,
                name=str(row["name"]),
            )
        )

    fk_rows = await connector.execute(_FK_FULL, mapping.source_schema)
    grouped: dict[str, dict[str, Any]] = {}
    for row in fk_rows:
        if str(row["table_name"]).lower() != mapping.source_table.lower():
            continue
        name = str(row["fk_name"])
        item = grouped.setdefault(
            name,
            {
                "columns": [],
                "referenced_columns": [],
                "referenced_schema": row["referenced_schema"],
                "referenced_table": row["referenced_table"],
                "delete_action": row["delete_action"],
                "update_action": row["update_action"],
            },
        )
        item["columns"].append(row["parent_column"])
        item["referenced_columns"].append(row["referenced_column"])
    for name, item in grouped.items():
        ref_schema = str(item["referenced_schema"])
        if mapping.source_schema == mapping.target_schema:
            target_ref_schema = ref_schema
        elif ref_schema.lower() == mapping.source_schema.lower():
            target_ref_schema = mapping.target_schema
        else:
            target_ref_schema = ref_schema
        try:
            sql = build_add_foreign_key_tsql(
                schema=mapping.target_schema,
                table=mapping.target_table,
                name=name,
                columns=item["columns"],
                referenced_schema=target_ref_schema,
                referenced_table=str(item["referenced_table"]),
                referenced_columns=item["referenced_columns"],
                delete_action=str(item["delete_action"] or "NO_ACTION"),
                update_action=str(item["update_action"] or "NO_ACTION"),
            )
        except ValueError:
            continue
        statements.append(
            SchemaCloneStatement(
                phase="post_copy",
                kind="foreign_key",
                sql=sql,
                schema=mapping.target_schema,
                name=name,
            )
        )

    trigger_rows = await connector.execute(
        """
        SELECT t.name AS trigger_name, m.definition
        FROM sys.triggers t
        INNER JOIN sys.sql_modules m ON t.object_id = m.object_id
        INNER JOIN sys.tables tb ON t.parent_id = tb.object_id
        INNER JOIN sys.schemas s ON tb.schema_id = s.schema_id
        WHERE s.name = ? AND tb.name = ?
        """,
        mapping.source_schema,
        mapping.source_table,
    )
    for row in trigger_rows:
        for batch in split_tsql_batches(str(row.get("definition") or "")):
            statements.append(
                SchemaCloneStatement(
                    phase="post_copy",
                    kind="trigger",
                    sql=batch,
                    schema=mapping.target_schema,
                    name=str(row["trigger_name"]),
                )
            )
    return statements


async def _mssql_modules(discovery: Any, database: str, schema: str) -> list[SchemaCloneStatement]:
    statements: list[SchemaCloneStatement] = []
    for kind, method in (
        ("function", discovery.discover_functions),
        ("view", discovery.discover_views),
        ("procedure", discovery.discover_procedures),
    ):
        objects = await method(database, schema)
        for obj in objects:
            definition = (obj.source_definition or "").strip()
            if not definition:
                continue
            for batch in split_tsql_batches(definition):
                statements.append(
                    SchemaCloneStatement(
                        phase="post_copy",
                        kind=kind,  # type: ignore[arg-type]
                        sql=batch,
                        schema=obj.schema_name,
                        name=obj.object_name,
                    )
                )
    return statements


async def _pg_table_plan(
    connector: Any,
    database: str,
    tables: list[TransferTableMapping],
    missing_targets: set[str],
    *,
    create_if_missing: bool,
    notes: list[str],
) -> list[SchemaCloneStatement]:
    from infrastructure.postgres.postgres_discovery import PostgresMetadataDiscovery

    if not create_if_missing:
        return []
    discovery = PostgresMetadataDiscovery(connector)
    statements: list[SchemaCloneStatement] = []
    schemas_emitted: set[str] = set()
    by_schema: dict[str, list[TransferTableMapping]] = {}
    for mapping in tables:
        by_schema.setdefault(mapping.source_schema, []).append(mapping)
    for source_schema, mappings in by_schema.items():
        discovered = await discovery.discover_tables(database, source_schema)
        table_by_name = {t.object_name.lower(): t for t in discovered}
        for mapping in mappings:
            if mapping.target_key.lower() not in missing_targets:
                continue
            src = table_by_name.get(mapping.source_table.lower())
            if src is None:
                continue
            if mapping.target_schema not in schemas_emitted:
                statements.append(
                    SchemaCloneStatement(
                        phase="pre_copy",
                        kind="schema",
                        sql=build_create_schema_pg(mapping.target_schema),
                        schema=mapping.target_schema,
                        name=mapping.target_schema,
                    )
                )
                schemas_emitted.add(mapping.target_schema)
            col_dicts = []
            for col in src.columns:
                dt = col.data_type
                pg_type = dt.type_name if dt else "text"
                if dt and dt.max_length and str(dt.type_name).lower() in {"character varying", "varchar", "character", "char"}:
                    pg_type = f"{dt.type_name}({dt.max_length})"
                col_dicts.append({
                    "name": col.column_name,
                    "pg_type": pg_type,
                    "nullable": col.is_nullable,
                    "default_value": col.default_value,
                    "is_computed": col.is_computed,
                })
            statements.append(
                SchemaCloneStatement(
                    phase="pre_copy",
                    kind="table",
                    sql=build_create_table_pg(
                        schema=mapping.target_schema,
                        table=mapping.target_table,
                        columns=col_dicts,
                        primary_key_columns=list(src.primary_key_columns or []),
                    ),
                    schema=mapping.target_schema,
                    name=mapping.target_table,
                )
            )
    if notes:
        notes.append("PostgreSQL → PostgreSQL clones tables only (not routines).")
    return statements


async def _mssql_to_pg_table_plan(
    connector: Any,
    database: str,
    tables: list[TransferTableMapping],
    missing_targets: set[str],
    *,
    create_if_missing: bool,
    notes: list[str],
) -> list[SchemaCloneStatement]:
    from infrastructure.sqlserver.sqlserver_discovery import SqlServerMetadataDiscovery

    if not create_if_missing:
        return []
    discovery = SqlServerMetadataDiscovery(connector)
    statements: list[SchemaCloneStatement] = []
    schemas_emitted: set[str] = set()
    by_schema: dict[str, list[TransferTableMapping]] = {}
    for mapping in tables:
        by_schema.setdefault(mapping.source_schema, []).append(mapping)
    for source_schema, mappings in by_schema.items():
        discovered = await discovery.discover_tables(database, source_schema)
        table_by_name = {t.object_name.lower(): t for t in discovered}
        for mapping in mappings:
            if mapping.target_key.lower() not in missing_targets:
                continue
            src = table_by_name.get(mapping.source_table.lower())
            if src is None:
                continue
            if mapping.target_schema not in schemas_emitted:
                statements.append(
                    SchemaCloneStatement(
                        phase="pre_copy",
                        kind="schema",
                        sql=f"CREATE SCHEMA IF NOT EXISTS {quote_pg_ident(mapping.target_schema)}",
                        schema=mapping.target_schema,
                        name=mapping.target_schema,
                    )
                )
                schemas_emitted.add(mapping.target_schema)
            col_dicts = []
            for col in src.columns:
                if col.is_computed:
                    continue
                dt = col.data_type
                pg_type = map_sqlserver_to_postgres_ddl(
                    dt.type_name if dt else "nvarchar",
                    max_length=dt.max_length if dt else None,
                    precision=dt.precision if dt else None,
                    scale=dt.scale if dt else None,
                )
                col_dicts.append({
                    "name": col.column_name,
                    "pg_type": pg_type,
                    "nullable": col.is_nullable,
                    "is_computed": False,
                })
            statements.append(
                SchemaCloneStatement(
                    phase="pre_copy",
                    kind="table",
                    sql=build_create_table_pg(
                        schema=mapping.target_schema,
                        table=mapping.target_table,
                        columns=col_dicts,
                        primary_key_columns=list(src.primary_key_columns or []),
                    ),
                    schema=mapping.target_schema,
                    name=mapping.target_table,
                )
            )
    notes.append(
        "SQL Server → PostgreSQL create-if-missing uses mapped PostgreSQL types, not T-SQL."
    )
    return statements


async def _rows_by_table(connector: Any, sql: str, schema: str) -> dict[str, list[dict[str, Any]]]:
    try:
        rows = await connector.execute(sql, schema)
    except Exception:
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(str(row["table_name"]).lower(), []).append(row)
    return out


async def _pk_by_table(connector: Any, schema: str) -> dict[str, dict[str, Any]]:
    try:
        rows = await connector.execute(_PK_NAMES, schema)
    except Exception:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = out.setdefault(
            str(row["table_name"]).lower(),
            {"name": row.get("pk_name"), "columns": []},
        )
        item["columns"].append(row["column_name"])
    return out
