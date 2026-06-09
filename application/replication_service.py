"""
Module: replication_service.py
Purpose: Replication application service — stream CRUD, schema checks, lifecycle control
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import struct
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from application.replication_runtime import get_runtime_manager
from domains.migration.target_schema_resolver import resolve_target_schema
from domains.replication.cdc_requirements import CdcStatus, validate_cdc_for_tables
from domains.replication.entities import ReplicationStreamConfig, StreamConcern, StreamTableConfig
from domains.replication.schema_drift_detector import TableSchemaSnapshot, detect_schema_drift
from domains.replication.validators import validate_identifier, validate_table_list
from infrastructure.metadata_db.models import ReplicationStreamRecord
from infrastructure.metadata_db.repositories.replication_stream_repository import (
    ReplicationStreamRepository,
)
from infrastructure.metadata_db.session import AsyncSessionFactory
from infrastructure.replication.capture_provider_factory import build_table_infos
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

def _connection_value_error(
    exc: Exception,
    *,
    conn_type: str,
    entry: dict[str, Any] | None,
) -> ValueError:
    from shared.errors.error_catalog import humanize_connection_message

    host = (entry or {}).get("host")
    default_port = 1433 if conn_type == "source" else 5432
    port = int((entry or {}).get("port", default_port))
    return ValueError(
        humanize_connection_message(
            str(exc),
            conn_type=conn_type,
            host=str(host) if host else None,
            port=port,
        ),
    )


_ACTIVE_STATES = frozenset({
    "STARTING", "SNAPSHOTTING", "CDC_CATCHUP", "CDC_STREAMING", "PAUSED",
})


def _build_table_config_rows(
    table_names: list[str],
    *,
    source_snapshots: list[TableSchemaSnapshot],
    target_snapshots: dict[str, TableSchemaSnapshot],
    source_schema: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table in table_names:
        src_snap = next(
            (s for s in source_snapshots if s.table_name.lower() == table.lower()),
            TableSchemaSnapshot(source_schema, table, ["id"], ["id"]),
        )
        tgt_snap = target_snapshots.get(table.lower())
        rows.append({
            "name": table,
            "pk_columns": src_snap.pk_columns,
            "target_table_name": tgt_snap.table_name if tgt_snap else table,
        })
    return rows


def _concern_to_dict(c: StreamConcern) -> dict[str, Any]:
    return {
        "level": c.level,
        "message": c.message,
        "table_name": c.table_name,
        "property_name": c.property_name,
    }


def _record_to_dict(
    record: ReplicationStreamRecord,
    *,
    runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = record.config_json or {}
    payload: dict[str, Any] = {
        "stream_id": record.replication_stream_id,
        "name": record.stream_name or cfg.get("name", ""),
        "status": record.status,
        "source_connection_id": record.project_connection_id,
        "target_connection_id": record.target_project_connection_id,
        "source_schema": cfg.get("source_schema", "dbo"),
        "target_schema": cfg.get("target_schema", "public"),
        "tables": cfg.get("tables", []),
        "mode": cfg.get("mode", "watermark"),
        "last_checkpoint_lsn": record.last_checkpoint_lsn,
        "error_message": record.error_message,
        "events_captured": record.events_captured,
        "events_applied": record.events_applied,
        "concerns": record.concerns_json or [],
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "stopped_at": record.stopped_at.isoformat() if record.stopped_at else None,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }
    if runtime:
        payload.update(runtime)
    return payload


def _merge_runtime(record: ReplicationStreamRecord, runtime: dict[str, Any] | None) -> dict[str, Any]:
    payload = _record_to_dict(record, runtime=runtime)
    if runtime:
        # Live runtime metrics override stale DB counters while the stream is active.
        payload["events_captured"] = int(runtime.get("events_captured", payload["events_captured"]))
        payload["events_applied"] = int(runtime.get("events_applied", payload["events_applied"]))
        payload["queue_depth"] = int(runtime.get("queue_depth", 0))
        payload["state"] = runtime.get("state", payload["status"])
        payload["is_active"] = True
        payload["is_running"] = runtime.get("is_running", False)
        payload["is_paused"] = runtime.get("is_paused", False)
        payload["pending_lag"] = int(runtime.get("pending_lag", 0))
    else:
        payload["is_active"] = False
        payload["is_running"] = False
        payload["is_paused"] = payload["status"] == "PAUSED"
        payload["pending_lag"] = max(
            0,
            int(payload.get("events_captured", 0)) - int(payload.get("events_applied", 0)),
        )
    return payload


async def list_streams() -> list[dict[str, Any]]:
    async with AsyncSessionFactory() as session:
        repo = ReplicationStreamRepository(session)
        records = await repo.list_streams()
    mgr = get_runtime_manager()
    out: list[dict[str, Any]] = []
    for rec in records:
        runtime = mgr.try_metrics_payload(rec.replication_stream_id)
        out.append(_merge_runtime(rec, runtime))
    return out


async def get_replication_summary() -> dict[str, Any]:
    """Aggregate live KPI metrics across all replication streams."""
    streams = await list_streams()
    active_statuses = {"CDC_STREAMING", "STARTING", "CDC_CATCHUP", "PAUSED"}
    active = [s for s in streams if s.get("status") in active_statuses or s.get("is_active")]
    captured = sum(int(s.get("events_captured", 0)) for s in streams)
    applied = sum(int(s.get("events_applied", 0)) for s in streams)
    queue_depth = sum(int(s.get("queue_depth", 0) or 0) for s in streams)
    return {
        "total_streams": len(streams),
        "active_streams": len(active),
        "stopped_streams": len(streams) - len(active),
        "events_captured": captured,
        "events_applied": applied,
        "queue_depth": queue_depth,
        "pending_lag": max(0, captured - applied),
        "live": any(s.get("is_active") for s in streams),
        "updated_at": datetime.now(UTC).isoformat(),
    }


async def fetch_cdc_status(
    source_connection_id: str,
    source_schema: str = "dbo",
) -> CdcStatus:
    """Query SQL Server for database- and table-level CDC enablement."""
    from apps.api.connection_store import get_decrypted_password, get_entry
    from infrastructure.sqlserver.sqlserver_connector import (
        SqlServerConnector,
        sqlserver_config_from_entry,
    )
    from infrastructure.sqlserver.sqlserver_discovery import SqlServerMetadataDiscovery

    entry = get_entry(source_connection_id)
    if not entry:
        raise ValueError(f"source connection {source_connection_id} not found")

    database = entry.get("database", "")
    if not database:
        raise ValueError("source connection has no database configured")

    password = get_decrypted_password(entry)
    connector = SqlServerConnector(
        sqlserver_config_from_entry({**entry, "database": database}, password=password),
    )
    try:
        await connector.connect()
    except Exception as exc:
        raise _connection_value_error(exc, conn_type="source", entry=entry) from exc
    try:
        discovery = SqlServerMetadataDiscovery(connector)
        raw = await discovery.discover_cdc_status(database, source_schema)
        return CdcStatus(
            db_enabled=bool(raw.get("db_cdc_enabled")),
            tables=dict(raw.get("tables") or {}),
        )
    finally:
        await connector.disconnect()


async def get_cdc_status(
    source_connection_id: str,
    source_schema: str = "dbo",
    tables: list[str] | None = None,
) -> dict[str, Any]:
    """Return CDC status for UI preflight checks."""
    status = await fetch_cdc_status(source_connection_id, source_schema)
    check_tables = tables if tables is not None else []
    error = validate_cdc_for_tables(status, check_tables)
    return {
        "db_cdc_enabled": status.db_enabled,
        "tables": status.tables,
        "ready": error is None,
        "message": error,
    }


async def _open_source_connector(connection_id: str) -> Any:
    from apps.api.connection_store import get_decrypted_password, get_entry
    from infrastructure.sqlserver.sqlserver_connector import (
        SqlServerConnector,
        sqlserver_config_from_entry,
    )

    entry = get_entry(connection_id)
    if not entry:
        raise ValueError(f"source connection {connection_id} not found")
    password = get_decrypted_password(entry)
    connector = SqlServerConnector(
        sqlserver_config_from_entry(entry, password=password),
    )
    try:
        await connector.connect()
    except Exception as exc:
        raise _connection_value_error(exc, conn_type="source", entry=entry) from exc
    return connector


async def _open_target_connector(connection_id: str) -> Any:
    from apps.api.connection_store import get_decrypted_password, get_entry
    from infrastructure.postgres.postgres_connector import (
        PostgresConnector,
        postgres_config_from_entry,
    )

    entry = get_entry(connection_id)
    if not entry:
        raise ValueError(f"target connection {connection_id} not found")
    password = get_decrypted_password(entry)
    connector = PostgresConnector(postgres_config_from_entry(entry, password=password))
    try:
        await connector.connect()
    except Exception as exc:
        raise _connection_value_error(exc, conn_type="target", entry=entry) from exc
    return connector


async def _fetch_schema_snapshots(
    *,
    source_connection_id: str,
    target_connection_id: str,
    tables: list[str],
    source_schema: str,
    target_schema: str,
) -> tuple[list[TableSchemaSnapshot], dict[str, TableSchemaSnapshot]]:
    """Load source/target column inventories for drift detection."""
    from infrastructure.postgres.postgres_discovery import PostgresMetadataDiscovery
    from infrastructure.sqlserver.sqlserver_discovery import SqlServerMetadataDiscovery

    src_schema = validate_identifier(source_schema)
    tgt_schema = validate_identifier(target_schema)
    validated_tables = validate_table_list(tables)

    source_connector = await _open_source_connector(source_connection_id)
    target_connector = await _open_target_connector(target_connection_id)
    try:
        src_discovery = SqlServerMetadataDiscovery(source_connector)
        database = source_connector._config.database  # type: ignore[attr-defined]

        src_tables = await src_discovery.discover_tables(database, src_schema)
        src_by_name = {t.object_name.lower(): t for t in src_tables}

        source_snapshots: list[TableSchemaSnapshot] = []
        target_snapshots: dict[str, TableSchemaSnapshot] = {}

        for table in validated_tables:
            src_table = src_by_name.get(table.lower())
            src_cols = [c.column_name for c in src_table.columns] if src_table else ["id"]
            src_pk = await _fetch_sqlserver_pk(source_connector, src_schema, table)
            source_snapshots.append(
                TableSchemaSnapshot(src_schema, table, src_cols, src_pk or ["id"]),
            )

            located = await _locate_postgres_table(
                target_connector,
                table=table,
                target_schema=tgt_schema,
                source_schema=src_schema,
            )
            if located is not None:
                found_schema, found_name = located
                tgt_cols = await _fetch_postgres_columns(
                    target_connector, found_schema, found_name,
                )
                tgt_pk = await _fetch_postgres_pk(
                    target_connector, found_schema, found_name,
                )
                target_snapshots[table.lower()] = TableSchemaSnapshot(
                    found_schema,
                    found_name,
                    tgt_cols or src_cols,
                    tgt_pk or src_pk or ["id"],
                )

        return source_snapshots, target_snapshots
    finally:
        await source_connector.disconnect()
        await target_connector.disconnect()


async def _fetch_sqlserver_pk(connector: Any, schema: str, table: str) -> list[str]:
    rows = await connector.execute(
        """
        SELECT c.name AS column_name
        FROM sys.key_constraints kc
        JOIN sys.index_columns ic
          ON ic.object_id = kc.parent_object_id AND ic.index_id = kc.unique_index_id
        JOIN sys.columns c
          ON c.object_id = ic.object_id AND c.column_id = ic.column_id
        WHERE kc.type = 'PK'
          AND kc.parent_object_id = OBJECT_ID(?)
        ORDER BY ic.key_ordinal
        """,
        {"full_name": f"{schema}.{table}"},
    )
    return [str(r["column_name"]) for r in rows]


async def _fetch_postgres_pk(connector: Any, schema: str, table: str) -> list[str]:
    rows = await connector.execute(
        """
        SELECT a.attname AS column_name
        FROM pg_index i
        JOIN pg_class c ON c.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(i.indkey)
        WHERE i.indisprimary
          AND lower(n.nspname) = lower($1)
          AND lower(c.relname) = lower($2)
        ORDER BY array_position(i.indkey, a.attnum)
        """,
        schema,
        table,
    )
    return [str(r["column_name"]) for r in rows]


def _target_table_name_candidates(table: str) -> list[str]:
    """PostgreSQL migrations typically lowercase unquoted table names."""
    names = [table]
    lower = table.lower()
    if lower not in names:
        names.append(lower)
    return names


def _alternate_schemas(target_schema: str, source_schema: str) -> list[str]:
    """Schemas to search when a table is missing from the resolved target schema."""
    seen: set[str] = set()
    alternates: list[str] = []
    for candidate in (target_schema, "public", source_schema):
        key = candidate.lower()
        if key not in seen:
            alternates.append(candidate)
            seen.add(key)
    return alternates


async def _locate_postgres_table(
    connector: Any,
    *,
    table: str,
    target_schema: str,
    source_schema: str,
) -> tuple[str, str] | None:
    """Return (schema, actual_table_name) when the table exists on PostgreSQL."""
    for candidate in _target_table_name_candidates(table):
        for schema in _alternate_schemas(target_schema, source_schema):
            actual = await _postgres_actual_table_name(connector, schema, candidate)
            if actual:
                return schema, actual
    return None


async def _postgres_actual_table_name(
    connector: Any,
    schema: str,
    table: str,
) -> str | None:
    rows = await connector.execute(
        """
        SELECT c.relname AS table_name
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE lower(n.nspname) = lower($1)
          AND lower(c.relname) = lower($2)
          AND c.relkind IN ('r', 'p')
        LIMIT 1
        """,
        schema,
        table,
    )
    return str(rows[0]["table_name"]) if rows else None


async def _fetch_postgres_columns(
    connector: Any,
    schema: str,
    table: str,
) -> list[str]:
    rows = await connector.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = $1
          AND lower(table_name) = lower($2)
        ORDER BY ordinal_position
        """,
        schema,
        table,
    )
    return [str(r["column_name"]) for r in rows]


async def check_target_migration_status(
    *,
    target_connection_id: str,
    target_schema: str,
    tables: list[str],
    source_schema: str = "dbo",
) -> list[dict[str, Any]]:
    """Return whether each source table already exists on the PostgreSQL target."""
    validated = validate_table_list(tables)
    tgt_schema = validate_identifier(
        resolve_target_schema(source_schema, target_schema),
    )
    connector = await _open_target_connector(target_connection_id)
    try:
        results: list[dict[str, Any]] = []
        for table in validated:
            located = await _locate_postgres_table(
                connector,
                table=table,
                target_schema=tgt_schema,
                source_schema=source_schema,
            )
            found_schema: str | None = located[0] if located else None
            found_name: str | None = located[1] if located else None
            row_count = (
                await _postgres_table_row_count(connector, found_schema, found_name)
                if found_schema and found_name
                else 0
            )

            exists = found_schema is not None
            schema_mismatch = bool(
                exists and found_schema and found_schema.lower() != tgt_schema.lower(),
            )
            if not exists:
                message = (
                    f"Table {table} is not on the target — run a migration for "
                    f"{source_schema}.{table} before starting replication."
                )
            elif row_count == 0:
                message = (
                    f"Table {found_name} exists in {found_schema} but is empty — "
                    "migrate data before relying on CDC."
                )
            elif schema_mismatch:
                message = (
                    f"Table found in schema {found_schema!r} (expected {tgt_schema!r}). "
                    "Update the target schema or move the table."
                )
            else:
                message = (
                    f"Table {found_name} is ready ({row_count:,} row(s) in {found_schema})."
                )

            results.append({
                "table_name": table,
                "exists": exists,
                "target_table_name": found_name,
                "found_in_schema": found_schema,
                "row_count": row_count,
                "schema_mismatch": schema_mismatch,
                "ready": exists and row_count > 0 and not schema_mismatch,
                "message": message,
            })
        return results
    finally:
        await connector.disconnect()


async def _postgres_table_exists(connector: Any, schema: str, table: str) -> bool:
    return await _postgres_actual_table_name(connector, schema, table) is not None


def _build_concerns_from_snapshots(
    *,
    tables: list[str],
    source_schema: str,
    target_schema: str,
    source_snapshots: list[TableSchemaSnapshot],
    target_snapshots: dict[str, TableSchemaSnapshot],
) -> list[StreamConcern]:
    concerns: list[StreamConcern] = []
    src_by_table = {s.table_name.lower(): s for s in source_snapshots}
    for table in tables:
        src_snap = src_by_table.get(
            table.lower(),
            TableSchemaSnapshot(source_schema, table, ["id"], ["id"]),
        )
        tgt_snap = target_snapshots.get(table.lower())
        concerns.extend(detect_schema_drift(src_snap, tgt_snap))
        if (
            tgt_snap is not None
            and tgt_snap.schema_name.lower() != target_schema.lower()
        ):
            concerns.append(StreamConcern(
                level="warning",
                message=(
                    f"Table {table} was found in schema {tgt_snap.schema_name!r} "
                    f"(stream target schema is {target_schema!r}). "
                    "Update the stream target schema if needed."
                ),
                table_name=table,
                property_name="target_schema",
            ))
    return concerns


async def _fetch_target_only_snapshots(
    *,
    target_connection_id: str,
    tables: list[str],
    source_schema: str,
    target_schema: str,
) -> tuple[dict[str, TableSchemaSnapshot], str]:
    """PostgreSQL-only table lookup — does not require SQL Server."""
    src_schema = validate_identifier(source_schema)
    tgt_schema = validate_identifier(resolve_target_schema(source_schema, target_schema))
    validated = validate_table_list(tables)
    target_connector = await _open_target_connector(target_connection_id)
    target_snapshots: dict[str, TableSchemaSnapshot] = {}
    try:
        for table in validated:
            located = await _locate_postgres_table(
                target_connector,
                table=table,
                target_schema=tgt_schema,
                source_schema=src_schema,
            )
            if located is None:
                continue
            found_schema, found_name = located
            tgt_cols = await _fetch_postgres_columns(
                target_connector, found_schema, found_name,
            )
            tgt_pk = await _fetch_postgres_pk(
                target_connector, found_schema, found_name,
            )
            target_snapshots[table.lower()] = TableSchemaSnapshot(
                found_schema,
                found_name,
                tgt_cols or ["id"],
                tgt_pk or ["id"],
            )
        return target_snapshots, tgt_schema
    finally:
        await target_connector.disconnect()


def _source_snapshots_from_config(
    cfg: dict[str, Any],
    *,
    source_schema: str,
    tables: list[str],
) -> list[TableSchemaSnapshot]:
    """Fallback source metadata from persisted stream config."""
    table_rows = {str(t["name"]).lower(): t for t in cfg.get("tables", [])}
    out: list[TableSchemaSnapshot] = []
    for table in tables:
        row = table_rows.get(table.lower(), {})
        out.append(
            TableSchemaSnapshot(
                source_schema,
                table,
                ["id"],
                list(row.get("pk_columns") or ["id"]),
            ),
        )
    return out


async def refresh_stream_concerns(stream_id: str) -> list[dict[str, Any]]:
    """Re-check target tables and refresh persisted concerns for a stream."""
    async with AsyncSessionFactory() as session:
        repo = ReplicationStreamRepository(session)
        record = await repo.get(stream_id)
    if record is None:
        raise ValueError(f"stream {stream_id} not found")

    cfg = dict(record.config_json or {})
    tables = [str(t["name"]) for t in cfg.get("tables", [])]
    src_schema = cfg.get("source_schema", "dbo")
    tgt_schema = validate_identifier(
        resolve_target_schema(src_schema, cfg.get("target_schema", "public")),
    )

    # Target-first: clears false "missing on target" blockers even when SQL Server is slow.
    target_snapshots, tgt_schema = await _fetch_target_only_snapshots(
        target_connection_id=record.target_project_connection_id or "",
        tables=tables,
        source_schema=src_schema,
        target_schema=tgt_schema,
    )
    discovered_schemas = {s.schema_name for s in target_snapshots.values()}
    if len(discovered_schemas) == 1:
        actual_schema = next(iter(discovered_schemas))
        if actual_schema.lower() != tgt_schema.lower():
            cfg["target_schema"] = actual_schema
            tgt_schema = actual_schema

    source_snapshots = _source_snapshots_from_config(cfg, source_schema=src_schema, tables=tables)
    if record.project_connection_id:
        try:
            full_src, full_tgt = await _fetch_schema_snapshots(
                source_connection_id=record.project_connection_id,
                target_connection_id=record.target_project_connection_id or "",
                tables=tables,
                source_schema=src_schema,
                target_schema=tgt_schema,
            )
            source_snapshots = full_src
            target_snapshots.update(full_tgt)
        except Exception as exc:
            logger.warning(
                "replication_source_snapshot_skipped",
                stream_id=stream_id,
                error=str(exc),
            )

    concerns = _build_concerns_from_snapshots(
        tables=tables,
        source_schema=src_schema,
        target_schema=tgt_schema,
        source_snapshots=source_snapshots,
        target_snapshots=target_snapshots,
    )
    concern_dicts = [_concern_to_dict(c) for c in concerns]
    cfg["tables"] = _build_table_config_rows(
        tables,
        source_snapshots=source_snapshots,
        target_snapshots=target_snapshots,
        source_schema=src_schema,
    )
    async with AsyncSessionFactory() as session:
        repo = ReplicationStreamRepository(session)
        await repo.update_record(
            stream_id,
            concerns_json=concern_dicts,
            config_json=cfg,
        )
    return concern_dicts


async def reconcile_stream_runtime(stream_id: str) -> str | None:
    """Mark DB status IDLE when the in-process runtime is gone (e.g. API restart)."""
    async with AsyncSessionFactory() as session:
        repo = ReplicationStreamRepository(session)
        record = await repo.get(stream_id)
    if record is None:
        return None
    if record.status not in _ACTIVE_STATES:
        return None
    if get_runtime_manager().get(stream_id):
        return None
    message = (
        "Replication runtime is not active (API may have restarted). "
        "Stop and start the stream to resume CDC capture."
    )
    async with AsyncSessionFactory() as session:
        repo = ReplicationStreamRepository(session)
        await repo.update_status(
            stream_id,
            status="IDLE",
            error_message=message,
        )
    return message


async def _postgres_table_row_count(connector: Any, schema: str, table: str) -> int:
    from shared.kernel.ddl_identifier import quote_pg_ident

    qualified = f"{quote_pg_ident(schema)}.{quote_pg_ident(table)}"
    try:
        rows = await connector.execute(f"SELECT COUNT(*) AS cnt FROM {qualified}")
        return int(rows[0]["cnt"]) if rows else 0
    except Exception:
        return 0


async def get_stream(stream_id: str) -> dict[str, Any] | None:
    async with AsyncSessionFactory() as session:
        repo = ReplicationStreamRepository(session)
        record = await repo.get(stream_id)
    if record is None:
        return None
    mgr = get_runtime_manager()
    runtime = mgr.try_metrics_payload(stream_id)
    return _merge_runtime(record, runtime)


def _connection_summary(connection_id: str | None) -> dict[str, Any] | None:
    if not connection_id:
        return None
    from apps.api.connection_store import get_entry

    entry = get_entry(connection_id)
    if not entry:
        return None
    return {
        "connection_id": connection_id,
        "name": entry.get("name", ""),
        "host": entry.get("host", ""),
        "port": entry.get("port"),
        "database": entry.get("database", ""),
        "type": entry.get("type", ""),
    }


async def _load_checkpoints(
    target_connection_id: str | None,
    target_schema: str,
    table_names: list[str],
) -> list[dict[str, Any]]:
    if not target_connection_id or not table_names:
        return []
    try:
        import asyncpg

        from apps.api.connection_store import get_decrypted_password, get_entry
        from apps.replicator.apply.checkpoint import CheckpointStore
        from apps.replicator.capture.models import LsnPosition

        entry = get_entry(target_connection_id)
        if not entry:
            return []
        password = get_decrypted_password(entry)
        conn = await asyncpg.connect(
            host=entry["host"],
            port=int(entry.get("port", 5432)),
            user=entry["username"],
            password=password,
            database=entry["database"],
        )
        try:
            store = CheckpointStore(conn)
            await store.ensure_table()
            rows: list[dict[str, Any]] = []
            for table in table_names:
                tgt_table = table.lower()
                cp = await store.load(target_schema, tgt_table)
                if cp is None:
                    continue
                try:
                    seg1, seg2, seg3 = struct.unpack(">IIH", cp.lsn_bytes)
                    lsn = LsnPosition(seg1, seg2, seg3)
                except Exception:
                    lsn = LsnPosition(0, 0, 0)
                rows.append({
                    "table_schema": cp.table_schema,
                    "table_name": cp.table_name,
                    "rows_applied": cp.rows_applied,
                    "last_checkpoint_lsn": lsn.to_string(),
                    "updated_at": cp.updated_at.isoformat() if cp.updated_at else None,
                })
            return rows
        finally:
            await conn.close()
    except Exception:
        logger.exception("replication_checkpoint_load_failed")
        return []


async def get_stream_details(stream_id: str) -> dict[str, Any] | None:
    """Return a rich live view of one replication stream for the detail page."""
    from application.replication_settings_config import resolved_replication_capture_settings

    platform_capture = resolved_replication_capture_settings()
    await reconcile_stream_runtime(stream_id)
    try:
        await refresh_stream_concerns(stream_id)
    except Exception:
        logger.exception("replication_refresh_concerns_failed", stream_id=stream_id)

    async with AsyncSessionFactory() as session:
        repo = ReplicationStreamRepository(session)
        record = await repo.get(stream_id)
    if record is None:
        return None

    mgr = get_runtime_manager()
    runtime = mgr.try_metrics_payload(stream_id, detailed=True)
    base = _merge_runtime(record, runtime)
    # concerns_json on base comes from refreshed record above
    cfg = record.config_json or {}
    table_names = [str(t["name"]) for t in cfg.get("tables", [])]
    src_schema = cfg.get("source_schema", "dbo")
    tgt_schema = cfg.get("target_schema", "public")

    target_tables: list[dict[str, Any]] = []
    try:
        if record.target_project_connection_id and table_names:
            target_tables = await check_target_migration_status(
                target_connection_id=record.target_project_connection_id,
                target_schema=tgt_schema,
                tables=table_names,
                source_schema=src_schema,
            )
    except Exception:
        logger.exception("replication_target_status_failed", stream_id=stream_id)

    checkpoints = await _load_checkpoints(
        record.target_project_connection_id,
        tgt_schema,
        table_names,
    )

    all_errors: list[str] = []
    if record.error_message:
        all_errors.append(record.error_message)
    if runtime:
        all_errors.extend(runtime.get("capture_errors") or [])
        all_errors.extend(runtime.get("apply_errors") or [])
        all_errors.extend(runtime.get("runtime_errors") or [])

    return {
        **base,
        "source_connection": _connection_summary(record.project_connection_id),
        "target_connection": _connection_summary(record.target_project_connection_id),
        "target_tables": target_tables,
        "checkpoints": checkpoints,
        "operations": (
            runtime.get("operations")
            if runtime
            else {"insert": 0, "update": 0, "delete": 0}
        ),
        "duplicates_skipped": runtime.get("duplicates_skipped", 0) if runtime else 0,
        "apply_failures": runtime.get("apply_failures", 0) if runtime else 0,
        "batches_polled": runtime.get("batches_polled", 0) if runtime else 0,
        "batches_with_changes": runtime.get("batches_with_changes", 0) if runtime else 0,
        "batch_size": (
            runtime.get("batch_size", platform_capture.batch_size)
            if runtime
            else platform_capture.batch_size
        ),
        "poll_interval_ms": (
            runtime.get("poll_interval_ms", platform_capture.poll_interval_ms)
            if runtime
            else platform_capture.poll_interval_ms
        ),
        "table_progress": runtime.get("table_progress", []) if runtime else [],
        "capture_errors": runtime.get("capture_errors", []) if runtime else [],
        "apply_errors": runtime.get("apply_errors", []) if runtime else [],
        "all_errors": all_errors,
        "mode": cfg.get("mode", "cdc"),
        "runtime_active": runtime is not None,
        "can_start": (
            record.status in {"IDLE", "COMPLETED", "FAILED", "STOPPED"}
            and not any(c.get("level") == "blocker" for c in (record.concerns_json or []))
        ),
    }


async def create_stream(
    *,
    name: str,
    source_connection_id: str,
    target_connection_id: str,
    tables: list[str],
    source_schema: str = "dbo",
    target_schema: str = "public",
    mode: str = "cdc",
    source_snapshots: list[TableSchemaSnapshot] | None = None,
    target_snapshots: dict[str, TableSchemaSnapshot] | None = None,
) -> dict[str, Any]:
    validated_tables = validate_table_list(tables)
    src_schema = validate_identifier(source_schema)
    tgt_schema = validate_identifier(target_schema)

    if mode != "cdc":
        raise ValueError("Replication requires CDC mode; watermark-only streams are not supported")

    tgt_schema = validate_identifier(resolve_target_schema(src_schema, tgt_schema))

    cdc_status = await fetch_cdc_status(source_connection_id, src_schema)
    cdc_error = validate_cdc_for_tables(cdc_status, validated_tables)
    if cdc_error:
        raise ValueError(cdc_error)

    if source_snapshots is None or target_snapshots is None:
        target_snapshots, tgt_schema = await _fetch_target_only_snapshots(
            target_connection_id=target_connection_id,
            tables=validated_tables,
            source_schema=src_schema,
            target_schema=tgt_schema,
        )
        discovered_schemas = {s.schema_name for s in target_snapshots.values()}
        if len(discovered_schemas) == 1:
            actual_schema = next(iter(discovered_schemas))
            if actual_schema.lower() != tgt_schema.lower():
                tgt_schema = actual_schema

        source_snapshots = _source_snapshots_from_config(
            {"tables": [{"name": t, "pk_columns": ["id"]} for t in validated_tables]},
            source_schema=src_schema,
            tables=validated_tables,
        )
        try:
            full_src, full_tgt = await _fetch_schema_snapshots(
                source_connection_id=source_connection_id,
                target_connection_id=target_connection_id,
                tables=validated_tables,
                source_schema=src_schema,
                target_schema=tgt_schema,
            )
            source_snapshots = full_src
            target_snapshots.update(full_tgt)
        except Exception as exc:
            logger.warning(
                "replication_source_snapshot_skipped",
                error=str(exc),
            )
    else:
        source_snapshots = source_snapshots or []
        target_snapshots = target_snapshots or {}

    concerns = _build_concerns_from_snapshots(
        tables=validated_tables,
        source_schema=src_schema,
        target_schema=tgt_schema,
        source_snapshots=source_snapshots,
        target_snapshots=target_snapshots,
    )

    stream_id = str(uuid4())
    table_configs = _build_table_config_rows(
        validated_tables,
        source_snapshots=source_snapshots or [],
        target_snapshots=target_snapshots or {},
        source_schema=src_schema,
    )
    config_json = {
        "name": name,
        "source_schema": src_schema,
        "target_schema": tgt_schema,  # resolved (dbo → public, etc.)
        "tables": table_configs,
        "mode": mode,
    }
    concern_dicts = [_concern_to_dict(c) for c in concerns]

    record = ReplicationStreamRecord(
        replication_stream_id=stream_id,
        project_connection_id=source_connection_id,
        target_project_connection_id=target_connection_id,
        stream_name=name,
        status="IDLE",
        config_json=config_json,
        concerns_json=concern_dicts,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    async with AsyncSessionFactory() as session:
        repo = ReplicationStreamRepository(session)
        await repo.create(record)

    logger.info(
        "replication_stream_created",
        stream_id=stream_id,
        tables=validated_tables,
        concern_count=len(concern_dicts),
    )
    return _record_to_dict(record)


_EDITABLE_STATES = frozenset({"IDLE", "COMPLETED", "FAILED", "STOPPED"})


async def update_stream(
    stream_id: str,
    *,
    name: str | None = None,
    source_connection_id: str | None = None,
    target_connection_id: str | None = None,
    tables: list[str] | None = None,
    source_schema: str | None = None,
    target_schema: str | None = None,
) -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        repo = ReplicationStreamRepository(session)
        record = await repo.get(stream_id)
    if record is None:
        raise ValueError(f"stream {stream_id} not found")

    mgr = get_runtime_manager()
    if mgr.get(stream_id):
        raise ValueError("stop the stream before editing its configuration")

    if record.status not in _EDITABLE_STATES:
        raise ValueError(
            f"cannot edit stream in status {record.status} — stop it first",
        )

    cfg = dict(record.config_json or {})
    src_conn = source_connection_id or record.project_connection_id or ""
    tgt_conn = target_connection_id or record.target_project_connection_id or ""
    table_names = validate_table_list(tables) if tables is not None else [
        str(t["name"]) for t in cfg.get("tables", [])
    ]
    src_schema = validate_identifier(source_schema or cfg.get("source_schema", "dbo"))
    tgt_schema = validate_identifier(
        resolve_target_schema(
            src_schema,
            target_schema or cfg.get("target_schema", "public"),
        ),
    )
    stream_name = (name or record.stream_name or cfg.get("name", stream_id)).strip()
    if not stream_name:
        raise ValueError("stream name is required")

    cdc_status = await fetch_cdc_status(src_conn, src_schema)
    cdc_error = validate_cdc_for_tables(cdc_status, table_names)
    if cdc_error:
        raise ValueError(cdc_error)

    source_snapshots, target_snapshots = await _fetch_schema_snapshots(
        source_connection_id=src_conn,
        target_connection_id=tgt_conn,
        tables=table_names,
        source_schema=src_schema,
        target_schema=tgt_schema,
    )
    concerns = _build_concerns_from_snapshots(
        tables=table_names,
        source_schema=src_schema,
        target_schema=tgt_schema,
        source_snapshots=source_snapshots,
        target_snapshots=target_snapshots,
    )

    table_configs = _build_table_config_rows(
        table_names,
        source_snapshots=source_snapshots,
        target_snapshots=target_snapshots,
        source_schema=src_schema,
    )

    new_cfg = {
        **cfg,
        "name": stream_name,
        "source_schema": src_schema,
        "target_schema": tgt_schema,
        "tables": table_configs,
        "mode": "cdc",
    }
    concern_dicts = [_concern_to_dict(c) for c in concerns]

    async with AsyncSessionFactory() as session:
        repo = ReplicationStreamRepository(session)
        updated = await repo.update_record(
            stream_id,
            stream_name=stream_name,
            project_connection_id=src_conn,
            target_project_connection_id=tgt_conn,
            config_json=new_cfg,
            concerns_json=concern_dicts,
            status="IDLE",
            error_message=None,
        )
    if updated is None:
        raise ValueError(f"stream {stream_id} not found")
    return _record_to_dict(updated)


async def delete_stream(stream_id: str) -> bool:
    mgr = get_runtime_manager()
    if mgr.get(stream_id):
        await mgr.stop_stream(stream_id)
    async with AsyncSessionFactory() as session:
        repo = ReplicationStreamRepository(session)
        return await repo.delete(stream_id)


async def start_stream(stream_id: str) -> dict[str, Any]:
    await reconcile_stream_runtime(stream_id)
    try:
        await refresh_stream_concerns(stream_id)
    except Exception:
        logger.exception("replication_refresh_concerns_failed", stream_id=stream_id)

    async with AsyncSessionFactory() as session:
        repo = ReplicationStreamRepository(session)
        record = await repo.get(stream_id)
    if record is None:
        raise ValueError(f"stream {stream_id} not found")
    if record.status in _ACTIVE_STATES:
        raise ValueError(f"stream {stream_id} is already active ({record.status})")

    blockers = [
        c for c in (record.concerns_json or [])
        if c.get("level") == "blocker"
    ]
    if blockers:
        raise ValueError(
            f"cannot start stream with blockers: {blockers[0].get('message')}"
        )

    cfg = record.config_json or {}
    table_names = [str(t["name"]) for t in cfg.get("tables", [])]
    src_schema = cfg.get("source_schema", "dbo")
    table_rows = cfg.get("tables", [])
    from application.replication_settings_config import resolved_replication_capture_settings

    capture_settings = resolved_replication_capture_settings()
    stream_config = ReplicationStreamConfig(
        stream_id=stream_id,
        name=record.stream_name or cfg.get("name", stream_id),
        source_connection_id=record.project_connection_id or "",
        target_connection_id=record.target_project_connection_id or "",
        source_schema=src_schema,
        target_schema=cfg.get("target_schema", "public"),
        tables=[
            StreamTableConfig(
                name=str(t["name"]),
                pk_columns=list(t.get("pk_columns") or ["id"]),
                watermark_column=t.get("watermark_column"),
                soft_delete_column=t.get("soft_delete_column"),
                target_table_name=str(t.get("target_table_name") or t["name"]),
            )
            for t in table_rows
        ],
        mode=cfg.get("mode", "cdc"),
        poll_interval_ms=capture_settings.poll_interval_ms,
        batch_size=capture_settings.batch_size,
    )

    target_conn = await _open_target_connection(record.target_project_connection_id)
    source_provider = await _build_source_provider(stream_config, validate_cdc=True)
    table_infos = build_table_infos(
        schema=stream_config.source_schema,
        table_names=table_names,
        pk_map={t.name.lower(): t.pk_columns for t in stream_config.tables},
        watermark_map={
            t.name.lower(): t.watermark_column or "modified"
            for t in stream_config.tables
        },
    )

    from apps.replicator.apply.checkpoint import CheckpointStore

    await CheckpointStore(target_conn).ensure_table()

    mgr = get_runtime_manager()
    runtime = await mgr.start_stream(
        stream_config,
        provider=source_provider,
        target_connection=target_conn,
        table_infos=table_infos,
    )
    runtime.concerns = list(record.concerns_json or [])
    if runtime.errors:
        raise ValueError(runtime.errors[0])

    async with AsyncSessionFactory() as session:
        repo = ReplicationStreamRepository(session)
        await repo.update_status(
            stream_id,
            status="CDC_STREAMING",
            started_at=datetime.now(UTC),
            stopped_at=None,
            error_message=None,
        )
        record = await repo.get(stream_id)

    return _merge_runtime(record, mgr.try_metrics_payload(stream_id))


async def stop_stream(stream_id: str) -> dict[str, Any]:
    mgr = get_runtime_manager()
    final_metrics: dict[str, Any] | None = mgr.try_metrics_payload(stream_id)
    await mgr.stop_stream(stream_id)
    async with AsyncSessionFactory() as session:
        repo = ReplicationStreamRepository(session)
        record = await repo.update_status(
            stream_id,
            status="COMPLETED",
            stopped_at=datetime.now(UTC),
            events_captured=int(final_metrics["events_captured"]) if final_metrics else None,
            events_applied=int(final_metrics["events_applied"]) if final_metrics else None,
        )
    if record is None:
        raise ValueError(f"stream {stream_id} not found")
    return _merge_runtime(record, None)


async def pause_stream(stream_id: str) -> dict[str, Any]:
    mgr = get_runtime_manager()
    await mgr.pause_stream(stream_id)
    async with AsyncSessionFactory() as session:
        repo = ReplicationStreamRepository(session)
        record = await repo.update_status(stream_id, status="PAUSED")
    if record is None:
        raise ValueError(f"stream {stream_id} not found")
    return _merge_runtime(record, mgr.try_metrics_payload(stream_id))


async def resume_stream(stream_id: str) -> dict[str, Any]:
    mgr = get_runtime_manager()
    await mgr.resume_stream(stream_id)
    async with AsyncSessionFactory() as session:
        repo = ReplicationStreamRepository(session)
        record = await repo.update_status(stream_id, status="CDC_STREAMING")
    if record is None:
        raise ValueError(f"stream {stream_id} not found")
    return _merge_runtime(record, mgr.try_metrics_payload(stream_id))


async def refresh_stream_metrics(stream_id: str) -> None:
    mgr = get_runtime_manager()
    payload = mgr.try_metrics_payload(stream_id)
    if not payload:
        return
    async with AsyncSessionFactory() as session:
        repo = ReplicationStreamRepository(session)
        await repo.update_status(
            stream_id,
            status=payload.get("state", "CDC_STREAMING"),
            events_captured=int(payload.get("events_captured", 0)),
            events_applied=int(payload.get("events_applied", 0)),
        )


async def stop_all_streams() -> int:
    mgr = get_runtime_manager()
    ids = mgr.list_active_ids()
    for sid in ids:
        await stop_stream(sid)
    return len(ids)


async def _build_source_provider(
    config: ReplicationStreamConfig,
    *,
    validate_cdc: bool = False,
) -> Any:
    """Build SQL Server CDC capture provider; raises ValueError with root cause on failure."""
    if not config.source_connection_id:
        raise ValueError("stream has no source connection configured")

    from apps.api.connection_store import get_entry
    from apps.replicator.capture.providers.cdc_provider import SqlServerCdcProvider
    from infrastructure.sqlserver.sqlserver_discovery import SqlServerMetadataDiscovery

    entry = get_entry(config.source_connection_id)
    if not entry:
        raise ValueError(f"source connection {config.source_connection_id} not found")

    connector = await _open_source_connector(config.source_connection_id)
    try:
        if validate_cdc:
            database = entry.get("database", "") or connector._config.database  # type: ignore[attr-defined]
            discovery = SqlServerMetadataDiscovery(connector)
            raw = await discovery.discover_cdc_status(database, config.source_schema)
            cdc_status = CdcStatus(
                db_enabled=bool(raw.get("db_cdc_enabled")),
                tables=dict(raw.get("tables") or {}),
            )
            table_names = [t.name for t in config.tables]
            cdc_error = validate_cdc_for_tables(cdc_status, table_names)
            if cdc_error:
                raise ValueError(cdc_error)

        provider = SqlServerCdcProvider(connector)
        dsn = (
            f"sqlserver://{entry.get('host', 'localhost')}/"
            f"{entry.get('database', '')}"
        )
        await provider.connect(dsn)
        return provider
    except ValueError:
        await connector.disconnect()
        raise
    except Exception as exc:
        await connector.disconnect()
        logger.exception(
            "replication_source_provider_failed",
            stream_id=config.stream_id,
        )
        raise _connection_value_error(exc, conn_type="source", entry=entry) from exc


async def _open_target_connection(connection_id: str | None) -> Any | None:
    if not connection_id:
        return None
    try:
        import asyncpg

        from apps.api.connection_store import get_decrypted_password, get_entry

        entry = get_entry(connection_id)
        if not entry:
            logger.warning("replication_target_connection_missing", connection_id=connection_id)
            return None
        from infrastructure.postgres.postgres_connector import resolve_postgres_ssl_mode

        password = get_decrypted_password(entry)
        ssl_mode = resolve_postgres_ssl_mode(entry)
        conn = await asyncpg.connect(
            host=entry["host"],
            port=int(entry.get("port", 5432)),
            user=entry["username"],
            password=password,
            database=entry["database"],
            ssl=ssl_mode,
        )
        return conn
    except Exception as exc:
        logger.exception("replication_target_connect_failed", connection_id=connection_id)
        raise _connection_value_error(exc, conn_type="target", entry=entry) from exc
