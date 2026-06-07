"""
Module: replication_service.py
Purpose: Replication application service — stream CRUD, schema checks, lifecycle control
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from application.replication_runtime import get_runtime_manager
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

_ACTIVE_STATES = frozenset({
    "STARTING", "SNAPSHOTTING", "CDC_CATCHUP", "CDC_STREAMING", "PAUSED",
})


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


async def list_streams() -> list[dict[str, Any]]:
    async with AsyncSessionFactory() as session:
        repo = ReplicationStreamRepository(session)
        records = await repo.list_streams()
    mgr = get_runtime_manager()
    out: list[dict[str, Any]] = []
    for rec in records:
        runtime = None
        if mgr.get(rec.replication_stream_id):
            runtime = mgr.status_payload(rec.replication_stream_id)
        out.append(_record_to_dict(rec, runtime=runtime))
    return out


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
    await connector.connect()
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


async def get_stream(stream_id: str) -> dict[str, Any] | None:
    async with AsyncSessionFactory() as session:
        repo = ReplicationStreamRepository(session)
        record = await repo.get(stream_id)
    if record is None:
        return None
    mgr = get_runtime_manager()
    runtime = mgr.status_payload(stream_id) if mgr.get(stream_id) else None
    return _record_to_dict(record, runtime=runtime)


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

    cdc_status = await fetch_cdc_status(source_connection_id, src_schema)
    cdc_error = validate_cdc_for_tables(cdc_status, validated_tables)
    if cdc_error:
        raise ValueError(cdc_error)

    concerns: list[StreamConcern] = []

    target_by_name = {s.table_name.lower(): s for s in (target_snapshots or {}).values()}
    for table in validated_tables:
        src_snap = None
        for s in source_snapshots or []:
            if s.table_name.lower() == table.lower():
                src_snap = s
                break
        if src_snap is None:
            src_snap = TableSchemaSnapshot(src_schema, table, columns=["id"], pk_columns=["id"])
        tgt_snap = target_by_name.get(table.lower())
        concerns.extend(detect_schema_drift(src_snap, tgt_snap))

    stream_id = str(uuid4())
    table_configs: list[dict[str, Any]] = []
    for table in validated_tables:
        snap = TableSchemaSnapshot(src_schema, table, columns=["id"], pk_columns=["id"])
        for s in source_snapshots or []:
            if s.table_name.lower() == table.lower():
                snap = s
                break
        table_configs.append({"name": table, "pk_columns": snap.pk_columns})
    config_json = {
        "name": name,
        "source_schema": src_schema,
        "target_schema": tgt_schema,
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


async def delete_stream(stream_id: str) -> bool:
    mgr = get_runtime_manager()
    if mgr.get(stream_id):
        await mgr.stop_stream(stream_id)
    async with AsyncSessionFactory() as session:
        repo = ReplicationStreamRepository(session)
        return await repo.delete(stream_id)


async def start_stream(stream_id: str) -> dict[str, Any]:
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
    if record.project_connection_id:
        cdc_status = await fetch_cdc_status(record.project_connection_id, src_schema)
        cdc_error = validate_cdc_for_tables(cdc_status, table_names)
        if cdc_error:
            raise ValueError(cdc_error)
    table_rows = cfg.get("tables", [])
    stream_config = ReplicationStreamConfig(
        stream_id=stream_id,
        name=record.stream_name or cfg.get("name", stream_id),
        source_connection_id=record.project_connection_id or "",
        target_connection_id=record.target_project_connection_id or "",
        source_schema=cfg.get("source_schema", "dbo"),
        target_schema=cfg.get("target_schema", "public"),
        tables=[
            StreamTableConfig(
                name=str(t["name"]),
                pk_columns=list(t.get("pk_columns") or ["id"]),
                watermark_column=t.get("watermark_column"),
                soft_delete_column=t.get("soft_delete_column"),
            )
            for t in table_rows
        ],
        mode=cfg.get("mode", "watermark"),
    )

    target_conn = await _open_target_connection(record.target_project_connection_id)
    source_provider = await _build_source_provider(stream_config)
    table_names = [t.name for t in stream_config.tables]
    table_infos = build_table_infos(
        schema=stream_config.source_schema,
        table_names=table_names,
        pk_map={t.name.lower(): t.pk_columns for t in stream_config.tables},
        watermark_map={
            t.name.lower(): t.watermark_column or "modified"
            for t in stream_config.tables
        },
    )

    mgr = get_runtime_manager()
    runtime = await mgr.start_stream(
        stream_config,
        provider=source_provider,
        target_connection=target_conn,
        table_infos=table_infos,
    )
    runtime.concerns = list(record.concerns_json or [])

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

    return _record_to_dict(record, runtime=mgr.status_payload(stream_id))


async def stop_stream(stream_id: str) -> dict[str, Any]:
    mgr = get_runtime_manager()
    await mgr.stop_stream(stream_id)
    async with AsyncSessionFactory() as session:
        repo = ReplicationStreamRepository(session)
        record = await repo.update_status(
            stream_id,
            status="COMPLETED",
            stopped_at=datetime.now(UTC),
        )
    if record is None:
        raise ValueError(f"stream {stream_id} not found")
    return _record_to_dict(record)


async def pause_stream(stream_id: str) -> dict[str, Any]:
    mgr = get_runtime_manager()
    await mgr.pause_stream(stream_id)
    async with AsyncSessionFactory() as session:
        repo = ReplicationStreamRepository(session)
        record = await repo.update_status(stream_id, status="PAUSED")
    if record is None:
        raise ValueError(f"stream {stream_id} not found")
    return _record_to_dict(record, runtime=mgr.status_payload(stream_id))


async def resume_stream(stream_id: str) -> dict[str, Any]:
    mgr = get_runtime_manager()
    await mgr.resume_stream(stream_id)
    async with AsyncSessionFactory() as session:
        repo = ReplicationStreamRepository(session)
        record = await repo.update_status(stream_id, status="CDC_STREAMING")
    if record is None:
        raise ValueError(f"stream {stream_id} not found")
    return _record_to_dict(record, runtime=mgr.status_payload(stream_id))


async def refresh_stream_metrics(stream_id: str) -> None:
    mgr = get_runtime_manager()
    if not mgr.get(stream_id):
        return
    payload = mgr.status_payload(stream_id)
    async with AsyncSessionFactory() as session:
        repo = ReplicationStreamRepository(session)
        await repo.update_status(
            stream_id,
            status=payload["state"],
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
) -> Any | None:
    """Build SQL Server CDC capture provider when source credentials are available."""
    if not config.source_connection_id:
        return None
    try:
        from apps.api.connection_store import get_decrypted_password, get_entry
        from apps.replicator.capture.providers.cdc_provider import SqlServerCdcProvider
        from infrastructure.sqlserver.sqlserver_connector import (
            SqlServerConnector,
            sqlserver_config_from_entry,
        )

        entry = get_entry(config.source_connection_id)
        if not entry:
            return None
        entry = {**entry, "password": get_decrypted_password(entry)}
        connector = SqlServerConnector(sqlserver_config_from_entry(entry))
        await connector.connect()
        provider = SqlServerCdcProvider(connector)
        await provider.connect("")
        return provider
    except Exception:
        logger.exception(
            "replication_source_provider_failed",
            stream_id=config.stream_id,
        )
        return None


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
        password = get_decrypted_password(entry)
        conn = await asyncpg.connect(
            host=entry["host"],
            port=int(entry.get("port", 5432)),
            user=entry["username"],
            password=password,
            database=entry["database"],
        )
        return conn
    except Exception:
        logger.exception("replication_target_connect_failed", connection_id=connection_id)
        return None
