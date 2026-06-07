# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""Temporal.io activity implementations for the migration workflow (L-9).

Activities accept ``connection_id`` references and resolve them via the
metadata DB + SecretsManager at execution time.  This keeps raw credentials
out of workflow inputs, aligns with the REST API's connection management, and
makes both control planes (REST and Temporal) use the same credential store.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from domains.chunking.chunk_planner import ChunkPlanner
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


async def _resolve_sqlserver_connector(connection_id: str, schema: str = "dbo"):
    """Fetch a SQL Server connection from the metadata DB and return a connected SqlServerConnector."""
    from application.workflow_bridge_service import WorkflowBridgeService
    from infrastructure.metadata_db.session import AsyncSessionFactory
    from infrastructure.sqlserver.sqlserver_connector import (
        SqlServerConnectionConfig,
        SqlServerConnector,
    )

    svc = WorkflowBridgeService(session_factory=AsyncSessionFactory, temporal_client=None)
    cfg = await svc.resolve_connection(connection_id)
    config = SqlServerConnectionConfig(
        host=cfg["host"],
        port=cfg["port"],
        database=cfg["database"],
        username=cfg["username"],
        password=cfg["password"],
        schema=schema,
    )
    connector = SqlServerConnector(config)
    await connector.connect()
    return connector


async def _resolve_postgres_connector(connection_id: str):
    """Fetch a PostgreSQL connection from the metadata DB and return a connected PostgresConnector."""
    from application.workflow_bridge_service import WorkflowBridgeService
    from infrastructure.metadata_db.session import AsyncSessionFactory
    from infrastructure.postgres.postgres_connector import (
        PostgresConnectionConfig,
        PostgresConnector,
    )

    svc = WorkflowBridgeService(session_factory=AsyncSessionFactory, temporal_client=None)
    cfg = await svc.resolve_connection(connection_id)
    config = PostgresConnectionConfig(
        host=cfg["host"],
        port=cfg["port"],
        database=cfg["database"],
        username=cfg["username"],
        password=cfg["password"],
    )
    connector = PostgresConnector(config)
    await connector.connect()
    return connector


async def discover_objects(connection_id: str, schema: str) -> list[dict]:
    from infrastructure.sqlserver.sqlserver_discovery import SqlServerMetadataDiscovery

    connector = await _resolve_sqlserver_connector(connection_id, schema)
    await connector.connect()
    try:
        discovery = SqlServerMetadataDiscovery(connector)
        tables = await discovery.discover_tables("source_db", schema)
        views = await discovery.discover_views("source_db", schema)
        procs = await discovery.discover_procedures("source_db", schema)
        funcs = await discovery.discover_functions("source_db", schema)
        result = []
        for t in tables:
            result.append({
                "object_id": str(t.object_id) if hasattr(t, "object_id") else "",
                "object_type": "TABLE",
                "name": t.object_name,
                "schema": t.schema_name,
                "source_definition": t.source_definition or "",
            })
        for v in views:
            result.append({
                "object_id": str(v.object_id) if hasattr(v, "object_id") else "",
                "object_type": "VIEW",
                "name": v.object_name,
                "schema": v.schema_name,
                "source_definition": v.source_definition or "",
            })
        for p in procs:
            result.append({
                "object_id": str(p.object_id) if hasattr(p, "object_id") else "",
                "object_type": "PROCEDURE",
                "name": p.object_name,
                "schema": p.schema_name,
                "source_definition": p.source_definition or "",
            })
        for f in funcs:
            result.append({
                "object_id": str(f.object_id) if hasattr(f, "object_id") else "",
                "object_type": "FUNCTION",
                "name": f.object_name,
                "schema": f.schema_name,
                "source_definition": f.source_definition or "",
            })
        return result
    finally:
        await connector.disconnect()


async def analyze_compatibility(objects: list[dict]) -> list[dict]:
    from domains.transpilation.procedural_converter import TSqlPatternMatcher

    from domains.transpilation.procedural_converter import ConversionDifficulty

    results = []
    high_difficulty = {ConversionDifficulty.COMPLEX, ConversionDifficulty.EXTREME}
    for obj in objects:
        sql = obj.get("source_definition", "")
        difficulty = TSqlPatternMatcher.detect_difficulty(sql)
        patterns = TSqlPatternMatcher.detect_patterns(sql)
        results.append({
            "object_id": obj.get("object_id", ""),
            "object_type": obj.get("object_type", ""),
            "name": obj.get("name", ""),
            "difficulty": difficulty.value,
            "patterns": patterns,
            "compatible": difficulty not in high_difficulty,
        })
    return results


async def convert_schema(object_id: str, sql: str) -> dict:
    from domains.transpilation.procedural_converter import ProceduralConverter

    converter = ProceduralConverter()
    result = converter.convert_procedure("dbo", "converted", [], sql)
    return {
        "object_id": object_id,
        "converted_sql": result.converted_sql,
        "success": result.success,
        "warnings": result.warnings,
        "errors": result.errors,
    }


async def generate_ddl(object_id: str, ir: dict) -> str:
    return f"-- DDL for {object_id}\n" + ir.get("converted_sql", "")


async def _get_pk_columns(source: Any, schema: str, table: str) -> list[str]:
    pk_query = """
        SELECT c.name AS column_name
        FROM sys.indexes i
        INNER JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id
        INNER JOIN sys.columns c ON i.object_id = c.object_id AND ic.column_id = c.column_id
        WHERE i.is_primary_key = 1
          AND OBJECT_SCHEMA_NAME(i.object_id) = ?
          AND OBJECT_NAME(i.object_id) = ?
        ORDER BY ic.key_ordinal
    """
    try:
        rows = await source.execute(pk_query, {"schema": schema, "table": table})
        return [r["column_name"] for r in rows]
    except Exception:
        return []


async def _get_approximate_row_count(source: Any, schema: str, table: str) -> int:
    try:
        rows = await source.execute("""
            SELECT SUM(p.rows) AS row_count
            FROM sys.partitions p
            INNER JOIN sys.objects o ON p.object_id = o.object_id
            INNER JOIN sys.schemas s ON o.schema_id = s.schema_id
            WHERE s.name = ? AND o.name = ? AND p.index_id IN (0, 1)
        """, {"schema": schema, "table": table})
        if rows and rows[0]["row_count"]:
            return rows[0]["row_count"]
    except Exception:
        pass
    try:
        rows = await source.execute(f"SELECT COUNT(*) AS cnt FROM [{schema}].[{table}]")
        return rows[0]["cnt"] if rows else 0
    except Exception:
        return 0


async def plan_chunks(source_connection_id: str, schema: str, table: str, chunk_size: int = 10000) -> dict:
    source = await _resolve_sqlserver_connector(source_connection_id, schema)
    await source.connect()
    try:
        planner = ChunkPlanner(source, chunk_size=chunk_size)
        chunking_result = await planner.plan_table(schema, table)
        return {
            "status": "planned",
            "table": table,
            "schema": schema,
            "column_name": chunking_result.column_name,
            "column_type": chunking_result.column_type.value,
            "total_chunks": len(chunking_result.chunks),
            "total_rows_estimate": chunking_result.total_rows_estimate,
            "min_value": str(chunking_result.min_value),
            "max_value": str(chunking_result.max_value),
            "chunks": [
                {
                    "chunk_id": str(c.chunk_id),
                    "start": str(c.boundary.start) if c.boundary else None,
                    "end": str(c.boundary.end) if c.boundary else None,
                    "hash": c.chunk_hash,
                }
                for c in chunking_result.chunks
            ],
        }
    finally:
        await source.disconnect()


async def migrate_table(
    source_connection_id: str,
    target_connection_id: str,
    schema: str,
    table: str,
    columns: list[str],
    chunk_size: int,
    parallel_workers: int,
) -> dict:
    logger.info(
        "Migrating table via Temporal activity",
        schema=schema,
        table=table,
        chunk_size=chunk_size,
        workers=parallel_workers,
    )
    try:
        source = await _resolve_sqlserver_connector(source_connection_id, schema)
        target = await _resolve_postgres_connector(target_connection_id)
        await source.connect()
        await target.connect()
        try:
            pk_cols = await _get_pk_columns(source, schema, table)
            order_col = pk_cols[0] if pk_cols else (columns[0] if columns else "id")
            total_rows = await _get_approximate_row_count(source, schema, table)

            col_list = columns if columns != ["*"] else []
            if not col_list:
                source_query = f"SELECT TOP 1 * FROM [{schema}].[{table}]"
                sample = await source.execute(source_query)
                col_list = list(sample[0].keys()) if sample else ["*"]

            col_str = ", ".join(f"[{c}]" for c in col_list)
            count = 0

            planner = ChunkPlanner(source, chunk_size=chunk_size)
            chunking_result = await planner.plan_table(schema, table)
            chunk_plans = chunking_result.chunks

            if not chunk_plans:
                logger.info("No chunks to migrate for table", table=table)
                return {"status": "completed", "rows_migrated": 0, "table": table}

            logger.info(
                "Migrating table with deterministic ranges",
                table=table,
                chunks=len(chunk_plans),
                column=chunking_result.column_name,
            )

            for idx, chunk_plan in enumerate(chunk_plans):
                if not chunk_plan.boundary:
                    continue

                range_query = (
                    f"SELECT {col_str} FROM [{schema}].[{table}] "
                    f"WHERE [{chunk_plan.column_name}] >= ? AND [{chunk_plan.column_name}] < ? "
                    f"ORDER BY [{order_col}] "
                    f"OPTION (MAXDOP 1)"
                )
                chunk = await source.execute(
                    range_query,
                    {"start": chunk_plan.boundary.start, "end": chunk_plan.boundary.end},
                )
                if not chunk:
                    continue

                tuples = [tuple(r.values()) for r in chunk]
                chunk_count = await target.copy_from_rows(table, col_list, tuples)
                count += chunk_count

                logger.info(
                    "Chunk migrated",
                    schema=schema,
                    table=table,
                    chunk=idx,
                    start=chunk_plan.boundary.start,
                    end=chunk_plan.boundary.end,
                    rows=chunk_count,
                    total=count,
                )

            return {"status": "completed", "rows_migrated": count, "table": table}
        finally:
            await source.disconnect()
            await target.disconnect()
    except Exception as e:
        logger.exception("Migration failed", schema=schema, table=table)
        return {"status": "failed", "error": str(e), "table": table}


async def validate_table(
    source_conn: str,
    target_conn: str,
    schema: str,
    table: str,
    *,
    target_schema: str = "public",
) -> dict:
    """Validate table row counts between source and target.

    ``source_conn`` and ``target_conn`` are connection_id strings from the
    metadata DB — resolved via WorkflowBridgeService.resolve_connection().
    """
    logger.info(
        "Validating table via Temporal activity",
        schema=schema,
        target_schema=target_schema,
        table=table,
    )
    try:
        source = await _resolve_sqlserver_connector(source_conn, schema)
        target = await _resolve_postgres_connector(target_conn)
        await source.connect()
        await target.connect()
        try:
            src_rows = await source.execute(f"SELECT COUNT(*) AS cnt FROM [{schema}].[{table}]")
            tgt_rows = await target.execute(
                f'SELECT COUNT(*) AS cnt FROM "{target_schema}"."{table}"',
            )
            src_count = src_rows[0]["cnt"] if src_rows else 0
            tgt_count = tgt_rows[0]["cnt"] if tgt_rows else 0
            passed = src_count == tgt_count
            return {
                "status": "passed" if passed else "failed",
                "source_count": src_count,
                "target_count": tgt_count,
                "table": table,
            }
        finally:
            await source.disconnect()
            await target.disconnect()
    except Exception as e:
        logger.exception("Validation failed", schema=schema, table=table)
        return {"status": "error", "error": str(e), "table": table}


async def send_notification(channel: str, message: str) -> None:
    logger.info("Notification sent", channel=channel, message=message)


async def create_snapshot_checkpoint(job_id: str, table: str, lsn: str) -> dict:
    """Legacy per-table checkpoint — delegates to save_cutover_checkpoint."""
    return await save_cutover_checkpoint(
        job_id, [table] if table else [], lsn=lsn,
    )


async def save_cutover_checkpoint(
    job_id: str,
    tables: list[str],
    lsn: str = "FINAL",
    schema: str = "dbo",
    target_schema: str = "public",
    snapshot_ref: str | None = None,
) -> dict:
    """Persist a durable cutover checkpoint for rollback (§13.2)."""
    from domains.orchestration.cutover_service import CutoverCheckpoint, CutoverService
    from infrastructure.metadata_db.session import AsyncSessionFactory

    async with AsyncSessionFactory() as session:
        svc = CutoverService(session)
        record = await svc.save_checkpoint(
            CutoverCheckpoint(
                job_id=job_id,
                tables=tables,
                schema=schema,
                target_schema=target_schema,
                checkpoint_lsn=lsn,
                snapshot_ref=snapshot_ref,
            )
        )
    logger.info("cutover_checkpoint_created", job_id=job_id, tables=tables, lsn=lsn)
    return {"success": True, "checkpoint_id": record.cutover_checkpoint_id, "tables": tables}


async def rollback_cutover(job_id: str, target_connection_id: str) -> dict:
    """Execute rollback to pre-cutover state by truncating target tables."""
    from domains.orchestration.cutover_service import CutoverService
    from infrastructure.metadata_db.session import AsyncSessionFactory

    target = await _resolve_postgres_connector(target_connection_id)
    try:
        async with AsyncSessionFactory() as session:
            svc = CutoverService(session, target_connector=target)
            result = await svc.rollback(job_id)
        logger.info("cutover_rollback_executed", job_id=job_id, success=result.get("success"))
        return result
    finally:
        await target.disconnect()


async def verify_target_snapshot(
    target_connection_id: str,
    tables: list[str],
    snapshot_ref: str | None,
    target_schema: str = "public",
) -> dict:
    """Verify or create pg_dump snapshot before cutover/migration (§13.3)."""
    from domains.migration.snapshot_gate import SnapshotGate

    target = await _resolve_postgres_connector(target_connection_id)
    try:
        gate = SnapshotGate()
        result = await gate.verify_or_create(
            target,
            database=target._config.database,
            tables=tables,
            schema=target_schema,
            require_snapshot=True,
            existing_ref=snapshot_ref,
        )
        return {
            "verified": result.verified,
            "snapshot_ref": result.snapshot_ref,
            "message": result.message,
            "created": result.created,
        }
    finally:
        await target.disconnect()


async def freeze_source_writes(
    source_connection_id: str,
    schema: str,
    tables: list[str],
    job_id: str,
) -> dict:
    """Capture baseline source row counts as write-freeze checkpoint (§13.2)."""
    from domains.orchestration.cutover_service import CutoverService
    from domains.orchestration.write_freeze import WriteFreezeCoordinator
    from infrastructure.metadata_db.session import AsyncSessionFactory

    source = await _resolve_sqlserver_connector(source_connection_id, schema)
    try:
        coordinator = WriteFreezeCoordinator(source)
        state = await coordinator.freeze(schema, tables)
        async with AsyncSessionFactory() as session:
            svc = CutoverService(session)
            await svc.record_write_freeze(
                job_id,
                frozen_at=state.frozen_at or datetime.now(UTC),
                source_row_counts=state.source_row_counts or {},
            )
        return {
            "frozen": state.frozen,
            "frozen_at": state.frozen_at.isoformat() if state.frozen_at else None,
            "source_row_counts": state.source_row_counts,
        }
    finally:
        await source.disconnect()


async def generate_connection_switch_manifest(
    job_id: str,
    source_connection_id: str,
    target_connection_id: str,
    tables: list[str],
    target_schema: str = "public",
) -> dict:
    """Build post-cutover connection switch manifest for operators."""
    from application.workflow_bridge_service import WorkflowBridgeService
    from domains.orchestration.connection_switch import ConnectionSwitchService
    from domains.orchestration.cutover_service import CutoverService
    from infrastructure.metadata_db.session import AsyncSessionFactory

    svc = WorkflowBridgeService(session_factory=AsyncSessionFactory, temporal_client=None)
    source_cfg = await svc.resolve_connection(source_connection_id)
    target_cfg = await svc.resolve_connection(target_connection_id)
    manifest = ConnectionSwitchService.build_manifest(
        job_id, source_cfg, target_cfg, tables, target_schema,
    )
    payload = {
        "job_id": manifest.job_id,
        "source_dsn": manifest.source_dsn,
        "target_dsn": manifest.target_dsn,
        "target_schema": manifest.target_schema,
        "tables": manifest.tables,
        "committed_at": manifest.committed_at,
        "instructions": manifest.instructions,
    }
    async with AsyncSessionFactory() as session:
        await CutoverService(session).store_connection_switch(job_id, payload)
    return payload


async def commit_cutover(
    job_id: str,
    source_connection_id: str = "",
    target_connection_id: str = "",
    tables: list[str] | None = None,
    target_schema: str = "public",
) -> dict:
    """Mark cutover committed, emit connection-switch manifest, close rollback window."""
    from domains.orchestration.cutover_service import CutoverService
    from infrastructure.metadata_db.session import AsyncSessionFactory

    manifest: dict = {}
    if source_connection_id and target_connection_id and tables:
        manifest = await generate_connection_switch_manifest(
            job_id, source_connection_id, target_connection_id, tables, target_schema,
        )
    async with AsyncSessionFactory() as session:
        svc = CutoverService(session)
        await svc.mark_committed(job_id)
    logger.info("cutover_committed", job_id=job_id)
    return {"success": True, "job_id": job_id, "connection_switch": manifest}
