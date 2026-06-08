# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""Schema discovery and table-mapping routes."""

from __future__ import annotations

import os
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from apps.api.connection_store import get_decrypted_password, get_entry
from apps.api.middleware.auth import UserRole, require_role
from domains.discovery.discovery_engine import DiscoveryEngine
from domains.discovery.pii_classifier import classify_column
from shared.errors.error_catalog import format_connection_error
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["discovery"])


def _raise_connection_error(exc: Exception, *, conn_type: str) -> None:
    raise HTTPException(status_code=502, detail=format_connection_error(str(exc), conn_type=conn_type))


# ---- Models ----

class DiscoverRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    connection_id: UUID
    connection_type: str = "source"
    host: str = ""
    port: int = 1433
    database: str = ""
    username: str = ""
    password: str = ""
    schema_name: str = Field(default="dbo", alias="schema")


class MappingColumnInfo(BaseModel):
    source_column: str
    source_type: str
    target_column: str
    target_type: str
    is_nullable: bool
    is_identity: bool
    conversion_notes: str = ""
    sensitivity: str | None = None


class MappingTableInfo(BaseModel):
    source_table: str
    target_table: str
    source_schema: str
    target_schema: str
    columns: list[MappingColumnInfo]
    row_count_estimate: int = 0
    warnings: list[str] = []


class MappingRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_connection_id: UUID
    target_connection_id: UUID
    tables: list[str]
    schema_name: str = Field(default="dbo", alias="schema")
    target_schema: str | None = None


class MappingResponse(BaseModel):
    source_connection_id: str
    target_connection_id: str
    tables: list[MappingTableInfo]


# ---- Endpoints ----

@router.post("/discover")
async def discover_schema(req: DiscoverRequest, _: dict = require_role(UserRole.OPERATOR)):
    entry = get_entry(str(req.connection_id)) if req.connection_id else None
    if entry:
        host = entry["host"]
        port = int(entry.get("port", 1433 if entry["type"] == "source" else 5432))
        database = entry["database"]
        username = entry.get("username", "")
        password = get_decrypted_password(entry)
        conn_type = entry["type"]
    else:
        host = req.host or os.environ.get("MIGRATION_SOURCE_HOST", "localhost")
        port = req.port or int(os.environ.get("MIGRATION_SOURCE_PORT", "1433"))
        database = req.database or os.environ.get("MIGRATION_SOURCE_DATABASE", "source_db")
        username = req.username or os.environ.get("MIGRATION_SOURCE_USER", "user")
        password = req.password or os.environ.get("MIGRATION_SOURCE_PASSWORD", "")
        conn_type = req.connection_type

    if conn_type == "source":
        from infrastructure.sqlserver.sqlserver_connector import (
            SqlServerConnectionConfig,
            SqlServerConnector,
            sqlserver_config_from_entry,
        )
        from infrastructure.sqlserver.sqlserver_discovery import SqlServerMetadataDiscovery
        if entry:
            connector = SqlServerConnector(sqlserver_config_from_entry(entry, password=password))
        else:
            connector = SqlServerConnector(SqlServerConnectionConfig(
                host=host, port=port, database=database, username=username, password=password,
                trust_server_certificate=os.environ.get(
                    "MIGRATION_SOURCE_TRUST_CERT", "false"
                ).lower() == "true",
            ))
    else:
        from infrastructure.postgres.postgres_connector import PostgresConnectionConfig, PostgresConnector
        from infrastructure.postgres.postgres_discovery import PostgresMetadataDiscovery
        connector = PostgresConnector(PostgresConnectionConfig(
            host=host, port=port, database=database, username=username, password=password,
        ))

    try:
        await connector.connect()
        if conn_type == "source":
            discovery = SqlServerMetadataDiscovery(connector)
        else:
            discovery = PostgresMetadataDiscovery(connector)
        engine = DiscoveryEngine(discovery)
        logger.debug("Starting discovery", database=database, schema=req.schema_name)
        result = await engine.discover_full(database, schemas=[req.schema_name])
        items = []
        for objs in [result.tables, result.views, result.procedures, result.functions]:
            for v in objs.values():
                items.extend(v)
        logger.debug("Discovery completed", database=database, objects_found=len(items))
        return {
            "connection_id": str(req.connection_id),
            "objects": len(items),
            "items": [
                {
                    "name": o.object_name,
                    "type": o.object_type.value if hasattr(o.object_type, "value") else str(o.object_type),
                    "schema": o.schema_name,
                }
                for o in items
            ],
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Discovery failed", database=database, error=str(exc))
        _raise_connection_error(exc, conn_type=conn_type)
    finally:
        await connector.disconnect()


class ListSchemasRequest(BaseModel):
    connection_id: UUID
    connection_type: str = "source"
    host: str = ""
    port: int = 0
    database: str = ""
    username: str = ""
    password: str = ""


@router.post("/list-schemas")
async def list_schemas(req: ListSchemasRequest, _: dict = require_role(UserRole.OPERATOR)):
    """Return the list of user-defined schemas for the given connection."""
    entry = get_entry(str(req.connection_id))
    if entry:
        conn_type = entry["type"]
        host = entry["host"]
        port = int(entry.get("port", 1433 if entry["type"] == "source" else 5432))
        database = entry["database"]
        username = entry.get("username", "")
        password = get_decrypted_password(entry)
    elif req.host and req.database and req.username:
        conn_type = req.connection_type
        host = req.host
        port = req.port or (1433 if conn_type == "source" else 5432)
        database = req.database
        username = req.username
        password = req.password
    else:
        raise HTTPException(status_code=404, detail=f"Connection {req.connection_id} not found")

    if conn_type == "source":
        from infrastructure.sqlserver.sqlserver_connector import (
            SqlServerConnectionConfig,
            SqlServerConnector,
            sqlserver_config_from_entry,
        )
        if entry:
            connector = SqlServerConnector(sqlserver_config_from_entry(entry, password=password))
        else:
            connector = SqlServerConnector(SqlServerConnectionConfig(
                host=host, port=port,
                database=database, username=username,
                password=password,
                trust_server_certificate=os.environ.get(
                    "MIGRATION_SOURCE_TRUST_CERT", "false"
                ).lower() == "true",
            ))
        schema_query = (
            "SELECT name FROM sys.schemas "
            "WHERE schema_id < 16384 "
            "AND name NOT IN ('sys','INFORMATION_SCHEMA','guest','db_owner',"
            "'db_accessadmin','db_securityadmin','db_ddladmin','db_backupoperator',"
            "'db_datareader','db_datawriter','db_denydatareader','db_denydatawriter') "
            "ORDER BY name"
        )
    else:
        from infrastructure.postgres.postgres_connector import PostgresConnectionConfig, PostgresConnector
        connector = PostgresConnector(PostgresConnectionConfig(
            host=host, port=port,
            database=database, username=username,
            password=password,
        ))
        schema_query = (
            "SELECT schema_name AS name FROM information_schema.schemata "
            "WHERE schema_name NOT IN ('pg_catalog','information_schema','pg_toast') "
            "AND schema_name NOT LIKE 'pg_%' "
            "ORDER BY schema_name"
        )

    try:
        await connector.connect()
        rows = await connector.execute(schema_query)
        schemas = [r["name"] for r in rows]
        return {"schemas": schemas}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to list schemas", error=str(exc))
        _raise_connection_error(exc, conn_type=conn_type)
    finally:
        await connector.disconnect()


class ObjectDefinitionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    connection_id: UUID
    schema_name: str = Field(..., alias="schema")
    name: str
    object_type: str


@router.post("/object-definition")
async def get_object_definition(req: ObjectDefinitionRequest, _: dict = require_role(UserRole.OPERATOR)):
    """Return the SQL definition or DDL for a stored procedure, function, or table."""
    entry = get_entry(str(req.connection_id))
    if not entry:
        raise HTTPException(status_code=404, detail=f"Connection {req.connection_id} not found")

    conn_type = entry["type"]
    password = get_decrypted_password(entry)
    obj_type = req.object_type.upper()

    if conn_type == "source":
        from infrastructure.sqlserver.sqlserver_connector import SqlServerConnector, sqlserver_config_from_entry
        connector = SqlServerConnector(sqlserver_config_from_entry(entry, password=password))
        try:
            await connector.connect()
            if obj_type in ("PROCEDURE", "STORED_PROCEDURE", "SP", "FUNCTION", "VIEW"):
                rows = await connector.execute(
                    "SELECT OBJECT_DEFINITION(OBJECT_ID(N'[' + ? + '].[' + ? + ']')) AS definition",
                    {"schema": req.schema_name, "name": req.name},
                )
                definition = rows[0]["definition"] if rows and rows[0]["definition"] else "-- Definition not available"
            else:
                # TABLE: build CREATE TABLE DDL from system catalog
                col_rows = await connector.execute(
                    """
                    SELECT c.name AS col_name,
                           tp.name AS type_name,
                           c.max_length, c.precision, c.scale,
                           c.is_nullable, c.is_identity,
                           OBJECT_DEFINITION(c.default_object_id) AS col_default
                    FROM sys.columns c
                    JOIN sys.types tp ON c.user_type_id = tp.user_type_id
                    WHERE c.object_id = OBJECT_ID(N'[' + ? + '].[' + ? + ']')
                    ORDER BY c.column_id
                    """,
                    {"schema": req.schema_name, "name": req.name},
                )
                if not col_rows:
                    definition = "-- Table not found or no columns"
                else:
                    col_defs = []
                    for c in col_rows:
                        t = c["type_name"]
                        if t in ("varchar", "nvarchar", "char", "nchar"):
                            ml = c["max_length"]
                            if ml == -1:
                                t += "(MAX)"
                            else:
                                t += f"({ml // 2 if t.startswith('n') else ml})"
                        elif t in ("decimal", "numeric"):
                            t += f"({c['precision']},{c['scale']})"
                        nullable = "NULL" if c["is_nullable"] else "NOT NULL"
                        identity = " IDENTITY(1,1)" if c["is_identity"] else ""
                        default = f" DEFAULT {c['col_default']}" if c["col_default"] else ""
                        col_defs.append(f"    [{c['col_name']}] {t}{identity}{default} {nullable}")

                    # Primary key
                    pk_rows = await connector.execute(
                        """
                        SELECT kc.name AS pk_name,
                               STRING_AGG('[' + c.name + ']', ', ') WITHIN GROUP (ORDER BY ic.key_ordinal) AS cols
                        FROM sys.key_constraints kc
                        JOIN sys.index_columns ic ON ic.object_id = kc.parent_object_id AND ic.index_id = kc.unique_index_id
                        JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
                        WHERE kc.type = 'PK' AND kc.parent_object_id = OBJECT_ID(N'[' + ? + '].[' + ? + ']')
                        GROUP BY kc.name
                        """,
                        {"schema": req.schema_name, "name": req.name},
                    )
                    if pk_rows:
                        col_defs.append(f"    CONSTRAINT [{pk_rows[0]['pk_name']}] PRIMARY KEY ({pk_rows[0]['cols']})")

                    definition = f"CREATE TABLE [{req.schema_name}].[{req.name}] (\n" + ",\n".join(col_defs) + "\n);\n"

                    # Indexes
                    idx_rows = await connector.execute(
                        """
                        SELECT i.name AS idx_name, i.is_unique,
                               STRING_AGG('[' + c.name + ']', ', ') WITHIN GROUP (ORDER BY ic.key_ordinal) AS cols
                        FROM sys.indexes i
                        JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
                        JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
                        WHERE i.object_id = OBJECT_ID(N'[' + ? + '].[' + ? + ']')
                          AND i.is_primary_key = 0 AND i.type > 0 AND ic.is_included_column = 0
                        GROUP BY i.name, i.is_unique
                        """,
                        {"schema": req.schema_name, "name": req.name},
                    )
                    for idx in idx_rows:
                        unique = "UNIQUE " if idx["is_unique"] else ""
                        definition += f"\nCREATE {unique}INDEX [{idx['idx_name']}] ON [{req.schema_name}].[{req.name}] ({idx['cols']});"

                    # Foreign keys
                    fk_rows = await connector.execute(
                        """
                        SELECT fk.name AS fk_name,
                               STRING_AGG('[' + c.name + ']', ', ') WITHIN GROUP (ORDER BY fkc.constraint_column_id) AS fk_cols,
                               OBJECT_SCHEMA_NAME(fk.referenced_object_id) AS ref_schema,
                               OBJECT_NAME(fk.referenced_object_id) AS ref_table,
                               STRING_AGG('[' + rc.name + ']', ', ') WITHIN GROUP (ORDER BY fkc.constraint_column_id) AS ref_cols
                        FROM sys.foreign_keys fk
                        JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
                        JOIN sys.columns c ON c.object_id = fkc.parent_object_id AND c.column_id = fkc.parent_column_id
                        JOIN sys.columns rc ON rc.object_id = fkc.referenced_object_id AND rc.column_id = fkc.referenced_column_id
                        WHERE fk.parent_object_id = OBJECT_ID(N'[' + ? + '].[' + ? + ']')
                        GROUP BY fk.name, fk.referenced_object_id
                        """,
                        {"schema": req.schema_name, "name": req.name},
                    )
                    for fk in fk_rows:
                        definition += (
                            f"\nALTER TABLE [{req.schema_name}].[{req.name}]"
                            f" ADD CONSTRAINT [{fk['fk_name']}]"
                            f" FOREIGN KEY ({fk['fk_cols']})"
                            f" REFERENCES [{fk['ref_schema']}].[{fk['ref_table']}] ({fk['ref_cols']});"
                        )

                    # Triggers
                    trig_rows = await connector.execute(
                        """
                        SELECT t.name AS trig_name, OBJECT_DEFINITION(t.object_id) AS trig_def
                        FROM sys.triggers t
                        WHERE t.parent_id = OBJECT_ID(N'[' + ? + '].[' + ? + ']')
                        """,
                        {"schema": req.schema_name, "name": req.name},
                    )
                    for trig in trig_rows:
                        if trig["trig_def"]:
                            definition += f"\n\n-- Trigger: {trig['trig_name']}\n{trig['trig_def']}"

            return {"definition": definition, "object_type": obj_type, "schema": req.schema_name, "name": req.name}
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Failed to get object definition", error=str(exc))
            raise HTTPException(status_code=502, detail=f"Failed to get definition: {exc}") from exc
        finally:
            await connector.disconnect()
    else:
        from infrastructure.postgres.postgres_connector import PostgresConnectionConfig, PostgresConnector
        connector = PostgresConnector(PostgresConnectionConfig(
            host=entry["host"], port=int(entry.get("port", 5432)),
            database=entry["database"], username=entry.get("username", ""),
            password=password,
        ))
        try:
            await connector.connect()
            if obj_type in ("PROCEDURE", "STORED_PROCEDURE", "SP", "FUNCTION"):
                rows = await connector.execute(
                    "SELECT pg_get_functiondef(p.oid) AS definition "
                    "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                    "WHERE p.proname = $1 AND n.nspname = $2 LIMIT 1",
                    req.name,
                    req.schema_name,
                )
                definition = rows[0]["definition"] if rows else "-- Definition not available"
            else:
                col_rows = await connector.execute(
                    "SELECT column_name, data_type, character_maximum_length, "
                    "numeric_precision, numeric_scale, is_nullable, column_default "
                    "FROM information_schema.columns "
                    "WHERE table_schema = $1 AND table_name = $2 "
                    "ORDER BY ordinal_position",
                    req.schema_name,
                    req.name,
                )
                if not col_rows:
                    definition = "-- Table not found or no columns"
                else:
                    from infrastructure.postgres.postgres_table_ddl import (
                        assemble_postgres_table_definition,
                    )
                    from shared.kernel.ddl_identifier import quote_pg_ident

                    col_defs = []
                    for c in col_rows:
                        t = c["data_type"]
                        if c["character_maximum_length"]:
                            t += f"({c['character_maximum_length']})"
                        elif c["numeric_precision"] and t in ("numeric", "decimal"):
                            t += f"({c['numeric_precision']},{c['numeric_scale']})"
                        nullable = "" if c["is_nullable"] == "YES" else " NOT NULL"
                        default = f" DEFAULT {c['column_default']}" if c["column_default"] else ""
                        col_defs.append(f"    {c['column_name']} {t}{default}{nullable}")

                    qualified = (
                        f"{quote_pg_ident(req.schema_name)}.{quote_pg_ident(req.name)}"
                    )
                    con_rows = await connector.execute(
                        f"SELECT conname, contype, pg_get_constraintdef(oid) AS condef "
                        f"FROM pg_constraint "
                        f"WHERE conrelid = '{qualified}'::regclass "
                        f"ORDER BY CASE contype WHEN 'p' THEN 0 WHEN 'u' THEN 1 "
                        f"WHEN 'c' THEN 2 ELSE 3 END, conname",
                    )
                    idx_rows = await connector.execute(
                        """
                        SELECT pg_get_indexdef(idx.indexrelid) AS indexdef
                        FROM pg_class rel
                        JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
                        JOIN pg_index idx ON idx.indrelid = rel.oid
                        WHERE nsp.nspname = $1
                          AND rel.relname = $2
                          AND NOT EXISTS (
                              SELECT 1
                              FROM pg_constraint con
                              WHERE con.conindid = idx.indexrelid
                                AND con.conrelid = rel.oid
                          )
                        ORDER BY idx.indexrelid
                        """,
                        req.schema_name,
                        req.name,
                    )
                    definition = assemble_postgres_table_definition(
                        req.schema_name,
                        req.name,
                        column_defs=col_defs,
                        constraints=con_rows,
                        secondary_indexes=[str(r["indexdef"]) for r in idx_rows],
                    )

            return {"definition": definition, "object_type": obj_type, "schema": req.schema_name, "name": req.name}
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Failed to get object definition (postgres)", error=str(exc))
            raise HTTPException(status_code=502, detail=f"Failed to get definition: {exc}") from exc
        finally:
            await connector.disconnect()


class ListDatabasesRequest(BaseModel):
    connection_id: UUID


@router.post("/list-databases")
async def list_databases(req: ListDatabasesRequest, _: dict = require_role(UserRole.OPERATOR)):
    """Return user databases for a SQL Server connection."""
    entry = get_entry(str(req.connection_id))
    if not entry:
        raise HTTPException(status_code=404, detail=f"Connection {req.connection_id} not found")

    if entry["type"] != "source":
        return {"databases": [entry["database"]]}

    password = get_decrypted_password(entry)
    from infrastructure.sqlserver.sqlserver_connector import SqlServerConnector, sqlserver_config_from_entry
    connector = SqlServerConnector(sqlserver_config_from_entry(entry, password=password))
    try:
        await connector.connect()
        rows = await connector.execute(
            "SELECT name FROM sys.databases "
            "WHERE database_id > 4 AND state_desc = 'ONLINE' "
            "AND name NOT IN ('model','msdb','tempdb') "
            "ORDER BY name"
        )
        return {"databases": [r["name"] for r in rows]}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to list databases", error=str(exc))
        return {"databases": [entry["database"]]}
    finally:
        await connector.disconnect()


class DependencyGraphRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    schema_name: str = Field(default="dbo", alias="schema")


@router.post("/connections/{connection_id}/dependency-graph")
async def get_dependency_graph(
    connection_id: UUID,
    req: DependencyGraphRequest,
    _: dict = require_role(UserRole.OPERATOR),
):
    """Return dependency graph nodes and edges for a SQL Server connection."""
    entry = get_entry(str(connection_id))
    if not entry:
        raise HTTPException(status_code=404, detail=f"Connection {connection_id} not found")

    if entry["type"] != "source":
        raise HTTPException(status_code=422, detail="Dependency graph requires a SQL Server (source) connection")

    password = get_decrypted_password(entry)
    from infrastructure.sqlserver.sqlserver_connector import SqlServerConnector, sqlserver_config_from_entry
    connector = SqlServerConnector(sqlserver_config_from_entry(entry, password=password))

    schema = req.schema_name

    try:
        await connector.connect()

        obj_rows = await connector.execute(
            "SELECT SCHEMA_NAME(schema_id) AS schema_name, name, type_desc "
            "FROM sys.objects "
            "WHERE is_ms_shipped = 0 "
            "AND SCHEMA_NAME(schema_id) = ? "
            "AND type IN ('P','FN','IF','TF','TR','V','U') "
            "ORDER BY name",
            {"schema": schema},
        )

        dep_rows = await connector.execute(
            "SELECT DISTINCT "
            "SCHEMA_NAME(ref.schema_id) AS referencing_schema, "
            "ref.name AS referencing_name, "
            "ref.type_desc AS referencing_type, "
            "COALESCE(dep.referenced_schema_name, ?) AS referenced_schema, "
            "dep.referenced_entity_name AS referenced_name, "
            "COALESCE(ref_obj.type_desc, 'UNKNOWN') AS referenced_type "
            "FROM sys.sql_expression_dependencies dep "
            "JOIN sys.objects ref ON ref.object_id = dep.referencing_id "
            "LEFT JOIN sys.objects ref_obj "
            "  ON ref_obj.name = dep.referenced_entity_name "
            "  AND ref_obj.schema_id = SCHEMA_ID(COALESCE(dep.referenced_schema_name, ?)) "
            "WHERE ref.is_ms_shipped = 0 "
            "AND dep.referenced_entity_name IS NOT NULL "
            "AND SCHEMA_NAME(ref.schema_id) = ? "
            "ORDER BY referencing_schema, referencing_name",
            {"default_schema": schema, "default_schema2": schema, "filter_schema": schema},
        )

        node_map: dict[str, dict] = {}
        for row in obj_rows:
            node_id = f"{row['schema_name']}.{row['name']}"
            node_map[node_id] = {
                "id": node_id,
                "label": row["name"],
                "schema": row["schema_name"],
                "type": row["type_desc"],
            }

        edges = []
        for row in dep_rows:
            src_key = f"{row['referencing_schema']}.{row['referencing_name']}"
            tgt_key = f"{row['referenced_schema']}.{row['referenced_name']}"
            if src_key not in node_map:
                node_map[src_key] = {
                    "id": src_key,
                    "label": row["referencing_name"],
                    "schema": row["referencing_schema"],
                    "type": row["referencing_type"],
                }
            if tgt_key not in node_map:
                node_map[tgt_key] = {
                    "id": tgt_key,
                    "label": row["referenced_name"],
                    "schema": row["referenced_schema"],
                    "type": row["referenced_type"],
                }
            edge_id = f"{src_key}->{tgt_key}"
            if not any(e["id"] == edge_id for e in edges):
                edges.append({"id": edge_id, "source": src_key, "target": tgt_key})

        return {
            "connection_id": str(connection_id),
            "schema": schema,
            "nodes": list(node_map.values()),
            "edges": edges,
            "node_count": len(node_map),
            "edge_count": len(edges),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to get dependency graph", error=str(exc))
        raise HTTPException(status_code=502, detail=f"Failed to get dependency graph: {exc}") from exc
    finally:
        await connector.disconnect()


@router.post("/mapping", response_model=MappingResponse)
async def get_table_mapping(req: MappingRequest, _: dict = require_role(UserRole.OPERATOR)):
    from domains.migration.target_schema_resolver import resolve_target_schema
    from domains.transpilation.type_mappings import get_type_mapping
    from infrastructure.sqlserver.sqlserver_connector import (
        SqlServerConnector,
        sqlserver_config_from_entry,
    )
    from infrastructure.sqlserver.sqlserver_discovery import SqlServerMetadataDiscovery

    src_entry = get_entry(str(req.source_connection_id))
    tgt_entry = get_entry(str(req.target_connection_id))
    if not src_entry or not tgt_entry:
        raise HTTPException(status_code=404, detail="Source or target connection not found")

    resolved_target_schema = resolve_target_schema(req.schema_name, req.target_schema)

    src_connector = SqlServerConnector(
        sqlserver_config_from_entry(src_entry, password=get_decrypted_password(src_entry))
    )
    await src_connector.connect()
    try:
        discovery = SqlServerMetadataDiscovery(src_connector)
        result = await discovery.discover_tables(src_entry["database"], req.schema_name)
        tables_map = {t.object_name: t for t in result}
        mapping_tables = []
        for table_name in req.tables:
            table_obj = tables_map.get(table_name)
            if not table_obj:
                mapping_tables.append(MappingTableInfo(
                    source_table=table_name, target_table=table_name.lower(),
                    source_schema=req.schema_name, target_schema=resolved_target_schema,
                    columns=[], warnings=[f"Table {table_name} not found in source"],
                ))
                continue
            mapping_columns = []
            for col in getattr(table_obj, "columns", []):
                source_type = col.data_type.type_name if hasattr(col.data_type, "type_name") else "unknown"
                try:
                    mapping = get_type_mapping(source_type)
                    target_type = getattr(mapping, "target_type", source_type)
                    notes = getattr(mapping, "notes", "")
                except Exception:
                    target_type = source_type
                    notes = f"No mapping defined for {source_type}"
                pii = classify_column(col.column_name)
                sensitivity = pii.sensitivity.value if pii.sensitivity.value != "none" else None
                mapping_columns.append(MappingColumnInfo(
                    source_column=col.column_name, source_type=source_type,
                    target_column=col.column_name.lower(), target_type=target_type,
                    is_nullable=getattr(col.data_type, "is_nullable", True),
                    is_identity=getattr(col, "is_identity", False),
                    conversion_notes=notes,
                    sensitivity=sensitivity,
                ))
            mapping_tables.append(MappingTableInfo(
                source_table=table_name, target_table=table_name.lower(),
                source_schema=req.schema_name, target_schema=resolved_target_schema,
                columns=mapping_columns,
                row_count_estimate=getattr(table_obj, "row_count_estimate", 0),
                warnings=[],
            ))
        return MappingResponse(
            source_connection_id=str(req.source_connection_id),
            target_connection_id=str(req.target_connection_id),
            tables=mapping_tables,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Table mapping failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"Mapping failed: {exc}") from exc
    finally:
        await src_connector.disconnect()
