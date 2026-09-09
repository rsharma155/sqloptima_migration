"""
Module: transfer_service.py
Purpose: Cross-Database Transfer control plane — catalog, preflight, job lifecycle.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from apps.api.connection_store import get_entry
from application.transfer_connector import make_transfer_connector
from domains.transfer.connection_engine import DatabaseEngine, infer_engine
from domains.transfer.preflight import TableInventory, compare_table, summarize_preflight
from domains.transfer.transfer_constraint_plan import (
    accept_constraint_plan,
    build_target_constraint_catalog,
    disable_items,
)
from domains.transfer.transfer_dispatch_config import build_transfer_dispatch_config
from domains.transfer.transfer_models import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    ConnectionEndpoint,
    TransferStatus,
    TransferTableMapping,
    TransferThreshold,
    constraint_plan_default,
    same_database,
)
from domains.transfer.transfer_path import TransferPath, engines_for, validate_path_engines
from infrastructure.metadata_db.models import TransferJobRecord
from infrastructure.metadata_db.repositories.transfer_job_repository import TransferJobRepository
from infrastructure.metadata_db.session import AsyncSessionFactory
from infrastructure.transfer.inventory import list_schema_tables, list_schemas, load_table_inventory
from shared.logging.structured_logging import get_logger
from shared.tenancy.project_scope import assert_resource_project_access

logger = get_logger(__name__)


class TransferError(ValueError):
    """User-facing Transfer validation error."""


def _require_entry(connection_id: UUID) -> dict:
    entry = get_entry(str(connection_id))
    if not entry:
        raise TransferError(f"Connection {connection_id} not found")
    return entry


def _endpoint(connection_id: UUID, schema: str = "") -> ConnectionEndpoint:
    entry = _require_entry(connection_id)
    return ConnectionEndpoint(
        connection_id=connection_id,
        engine=infer_engine(entry).value,
        host=str(entry.get("host") or ""),
        port=int(entry.get("port") or 0),
        database=str(entry.get("database") or ""),
        schema_name=schema,
    )


def _assert_pair(path: TransferPath, source_id: UUID, target_id: UUID) -> tuple[dict, dict, ConnectionEndpoint, ConnectionEndpoint]:
    if source_id == target_id:
        raise TransferError("Source and target must be different connections")
    src_entry = _require_entry(source_id)
    tgt_entry = _require_entry(target_id)
    src_engine = infer_engine(src_entry)
    tgt_engine = infer_engine(tgt_entry)
    validate_path_engines(path, src_engine, tgt_engine)
    src = _endpoint(source_id)
    tgt = _endpoint(target_id)
    if same_database(src, tgt):
        raise TransferError(
            "Source and destination must be different databases "
            f"({src.host}:{src.port}/{src.database})"
        )
    if tgt.engine == DatabaseEngine.POSTGRES.value and tgt.database.strip().lower() == "postgres":
        raise TransferError("The default 'postgres' database cannot be used as a Transfer target")
    return src_entry, tgt_entry, src, tgt


def _job_to_dict(job: TransferJobRecord) -> dict[str, Any]:
    settings = job.runtime_settings
    tables = [
        {
            "source_schema": p.source_schema,
            "source_table": p.source_table,
            "target_schema": p.target_schema,
            "target_table": p.target_table,
            "status": p.status,
            "rows_copied": p.rows_copied,
            "row_count_estimate": p.row_count_estimate,
            "chunk_size": p.chunk_size,
            "columns": p.columns or [],
            "error": getattr(p, "error", None),
            "error_count": int(getattr(p, "error_count", 0) or 0),
            "error_at": p.error_at.isoformat() if getattr(p, "error_at", None) else None,
        }
        for p in (job.table_plans or [])
    ]
    percent = 0.0
    if job.rows_total:
        percent = min(100.0, round(100.0 * job.rows_copied / job.rows_total, 1))
    return {
        "job_id": job.transfer_job_id,
        "path": job.path,
        "status": job.status,
        "phase": job.phase,
        "source_connection_id": job.source_project_connection_id,
        "target_connection_id": job.target_project_connection_id,
        "project_id": job.project_id,
        "tables_total": job.tables_total,
        "tables_done": job.tables_done,
        "rows_copied": job.rows_copied,
        "rows_total": job.rows_total,
        "overall_percentage": percent,
        "error": job.error,
        "preflight": job.preflight_json,
        "constraint_plan": job.constraint_plan,
        "tables": tables,
        "threshold": {
            "chunk_size": settings.chunk_size if settings else 10_000,
            "min_chunk_size": settings.min_chunk_size if settings else 1_000,
            "max_chunk_size": settings.max_chunk_size if settings else 100_000,
            "max_rows_per_sec": settings.max_rows_per_sec if settings else None,
        },
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def _table_percent(rows_copied: int, row_count_estimate: int) -> float:
    if not row_count_estimate:
        return 0.0
    return min(100.0, round(100.0 * rows_copied / row_count_estimate, 1))


def _table_key(schema: str, table: str) -> str:
    return f"{schema}.{table}"


def build_live_metrics(job: dict[str, Any]) -> dict[str, Any]:
    """Job-wide live snapshot used by the Transfer metrics dashboard."""
    tables_out: list[dict[str, Any]] = []
    failed = 0
    running = 0
    completed = 0
    for table in job.get("tables") or []:
        status = str(table.get("status") or "pending")
        error = table.get("error")
        if status == "failed" or error:
            failed += 1
        elif status in {"running", "copying", "loading"}:
            running += 1
        elif status == "completed":
            completed += 1
        rows_copied = int(table.get("rows_copied") or 0)
        estimate = int(table.get("row_count_estimate") or 0)
        source_schema = str(table.get("source_schema") or "")
        source_table = str(table.get("source_table") or "")
        tables_out.append({
            "table_key": _table_key(source_schema, source_table),
            "source_schema": source_schema,
            "source_table": source_table,
            "target_schema": str(table.get("target_schema") or ""),
            "target_table": str(table.get("target_table") or ""),
            "status": status,
            "rows_copied": rows_copied,
            "row_count_estimate": estimate,
            "percent": _table_percent(rows_copied, estimate),
            "chunk_size": int(table.get("chunk_size") or 0),
            "error": error,
            "error_count": int(table.get("error_count") or 0),
            "error_at": table.get("error_at"),
        })
    return {
        "job_id": job.get("job_id"),
        "status": job.get("status"),
        "phase": job.get("phase"),
        "overall_percentage": job.get("overall_percentage") or 0.0,
        "total_rows_copied": int(job.get("rows_copied") or 0),
        "total_rows_estimate": int(job.get("rows_total") or 0),
        "tables_total": int(job.get("tables_total") or len(tables_out)),
        "tables_done": int(job.get("tables_done") or 0),
        "tables_completed": completed,
        "tables_running": running,
        "tables_failed": failed,
        "effective_chunk_size": (job.get("threshold") or {}).get("chunk_size") or 10_000,
        "tables": tables_out,
    }


async def catalog_schemas(connection_id: UUID) -> list[str]:
    entry = _require_entry(connection_id)
    engine = infer_engine(entry)
    connector, _ = await make_transfer_connector(entry)
    await connector.connect()
    try:
        return await list_schemas(connector, engine, str(entry.get("database") or ""))
    finally:
        await connector.disconnect()


async def catalog_tables(connection_id: UUID, schema: str) -> list[dict[str, Any]]:
    entry = _require_entry(connection_id)
    engine = infer_engine(entry)
    connector, _ = await make_transfer_connector(entry)
    await connector.connect()
    try:
        return await list_schema_tables(connector, engine, str(entry.get("database") or ""), schema)
    finally:
        await connector.disconnect()


async def run_preflight(
    *,
    path: TransferPath,
    source_connection_id: UUID,
    target_connection_id: UUID,
    tables: list[TransferTableMapping],
    create_if_missing: bool = False,
) -> dict[str, Any]:
    if not tables:
        raise TransferError("Select at least one table")
    src_entry, tgt_entry, src, tgt = _assert_pair(path, source_connection_id, target_connection_id)
    src_engine = infer_engine(src_entry)
    tgt_engine = infer_engine(tgt_entry)

    src_conn, _ = await make_transfer_connector(src_entry)
    tgt_conn, _ = await make_transfer_connector(tgt_entry)
    await src_conn.connect()
    await tgt_conn.connect()
    try:
        table_reports = []
        job_target_keys = {t.target_key.lower() for t in tables}
        for mapping in tables:
            source_inv = await load_table_inventory(
                src_conn, src_engine, src.database, mapping.source_schema, mapping.source_table,
            )
            target_inv = await load_table_inventory(
                tgt_conn, tgt_engine, tgt.database, mapping.target_schema, mapping.target_table,
            )
            if not source_inv.exists:
                table_reports.append({
                    "source": {"schema": mapping.source_schema, "table": mapping.source_table},
                    "target": {"schema": mapping.target_schema, "table": mapping.target_table},
                    "existence": "missing_source",
                    "row_count_source": 0,
                    "row_count_target": target_inv.row_count if target_inv.exists else 0,
                    "columns": {
                        "matched": [],
                        "missing_on_target": [],
                        "extra_on_target": [],
                        "type_mismatches": [],
                        "nullability_mismatches": [],
                    },
                    "constraints": [],
                    "indexes": [],
                    "foreign_keys": [],
                    "triggers": [],
                    "identity": None,
                    "has_blocker": True,
                    "warning_count": 0,
                    "message": "Source table does not exist",
                })
                continue
            table_reports.append(
                compare_table(
                    path=path,
                    source=source_inv,
                    target=target_inv if target_inv.exists else TableInventory(
                        schema=mapping.target_schema, table=mapping.target_table, exists=False,
                    ),
                    create_if_missing=create_if_missing,
                    tables_in_job=job_target_keys,
                )
            )
    finally:
        await src_conn.disconnect()
        await tgt_conn.disconnect()

    conflicts = await _overlapping_jobs(
        source_connection_id=str(source_connection_id),
        target_connection_id=str(target_connection_id),
        target_keys=job_target_keys,
    )
    summary = summarize_preflight(table_reports, extra_blockers=1 if conflicts else 0)
    if conflicts:
        summary["can_start"] = False
    return {
        "path": path.value,
        "source": src.model_dump(mode="json"),
        "target": tgt.model_dump(mode="json"),
        "same_server": src.host.strip().lower() == tgt.host.strip().lower() and src.port == tgt.port,
        "tables": table_reports,
        "target_constraints": build_target_constraint_catalog(table_reports),
        "job_conflicts": conflicts,
        "summary": summary,
        "can_start": summary["can_start"],
    }


async def create_job(
    *,
    path: TransferPath,
    source_connection_id: UUID,
    target_connection_id: UUID,
    tables: list[TransferTableMapping],
    threshold: TransferThreshold,
    constraint_plan: dict[str, Any] | None,
    create_if_missing: bool,
    project_id: str | None,
) -> dict[str, Any]:
    report = await run_preflight(
        path=path,
        source_connection_id=source_connection_id,
        target_connection_id=target_connection_id,
        tables=tables,
        create_if_missing=create_if_missing,
    )
    if not report["can_start"]:
        raise TransferError(
            "Preflight has blockers — resolve missing tables, type mismatches, "
            "or overlapping jobs before starting"
        )
    src_entry = _require_entry(source_connection_id)
    tgt_entry = _require_entry(target_connection_id)
    resolved_project = project_id or src_entry.get("project_id")
    catalog = build_target_constraint_catalog(report["tables"])
    try:
        plan = accept_constraint_plan(
            constraint_plan,
            catalog,
            on_stop=(constraint_plan or {}).get("on_stop") or constraint_plan_default()["on_stop"],
            create_if_missing=create_if_missing,
        )
    except ValueError as exc:
        raise TransferError(str(exc)) from exc
    plan["create_if_missing"] = create_if_missing
    rows_total = sum(int(t.get("row_count_source") or 0) for t in report["tables"])
    table_rows = []
    estimates = {f"{t['source']['schema']}.{t['source']['table']}".lower(): t for t in report["tables"]}
    for mapping in tables:
        info = estimates.get(mapping.source_key.lower()) or {}
        table_rows.append({
            "source_schema": mapping.source_schema,
            "source_table": mapping.source_table,
            "target_schema": mapping.target_schema,
            "target_table": mapping.target_table,
            "columns": mapping.columns,
            "row_count_estimate": int(info.get("row_count_source") or 0),
        })
    job_id = uuid4()
    from application.transfer_settings_config import resolved_file_offload

    dispatch = build_transfer_dispatch_config(
        job_id=job_id,
        path=path,
        source_connection_id=source_connection_id,
        target_connection_id=target_connection_id,
        source_engine=infer_engine(src_entry).value,
        target_engine=infer_engine(tgt_entry).value,
        tables=table_rows,
        threshold=threshold.model_dump(),
        constraint_plan=plan,
        preflight=report,
        file_offload=resolved_file_offload(),
    )
    table_rows = [
        {
            "source_schema": t.source_schema,
            "source_table": t.source_table,
            "target_schema": t.target_schema,
            "target_table": t.target_table,
            "columns": list(t.columns),
            "row_count_estimate": t.row_count_estimate,
        }
        for t in dispatch.tables
    ]
    async with AsyncSessionFactory() as session:
        repo = TransferJobRepository(session)
        job = await repo.create(
            job_id=str(job_id),
            path=path.value,
            source_connection_id=str(source_connection_id),
            target_connection_id=str(target_connection_id),
            project_id=resolved_project,
            tables=table_rows,
            threshold=threshold.model_dump(),
            constraint_plan=plan,
            preflight_json=report,
            config=dispatch.to_dict(),
            rows_total=rows_total,
        )
        await repo.add_constraint_actions(job.transfer_job_id, disable_items(plan))
        await repo.append_log(job.transfer_job_id, "Transfer job queued — waiting for Go transfer worker")
        await repo.issue_command(job.transfer_job_id, "START")
        job = await repo.get(job.transfer_job_id)
    assert job is not None
    return _job_to_dict(job)


async def list_jobs(project_id: str | None = None) -> list[dict[str, Any]]:
    async with AsyncSessionFactory() as session:
        jobs = await TransferJobRepository(session).list_jobs(project_id)
    return [_job_to_dict(j) for j in jobs]


async def get_job(job_id: UUID, *, user_project_id: str | None, is_admin: bool) -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        job = await TransferJobRepository(session).get(str(job_id))
    if job is None:
        raise KeyError(str(job_id))
    assert_resource_project_access(job.project_id, user_project_id=user_project_id, is_admin=is_admin)
    return _job_to_dict(job)


async def get_live_metrics(job_id: UUID, *, user_project_id: str | None, is_admin: bool) -> dict[str, Any]:
    return build_live_metrics(
        await get_job(job_id, user_project_id=user_project_id, is_admin=is_admin)
    )


async def list_logs(
    job_id: UUID,
    *,
    after_id: int = 0,
    limit: int = 200,
    table_name: str | None = None,
) -> list[dict[str, Any]]:
    async with AsyncSessionFactory() as session:
        rows = await TransferJobRepository(session).list_logs(
            str(job_id), after_id=after_id, limit=limit, table_name=table_name,
        )
    return [
        {
            "id": r.transfer_job_log_id,
            "logged_at": r.logged_at.isoformat() if r.logged_at else None,
            "level": r.level,
            "phase": r.phase,
            "table_name": r.table_name,
            "message": r.message,
        }
        for r in rows
    ]


async def pause_job(job_id: UUID) -> dict[str, Any]:
    return await _command(job_id, "PAUSE", TransferStatus.PAUSED, allowed={TransferStatus.RUNNING, TransferStatus.PREPARING, TransferStatus.QUEUED})


async def resume_job(job_id: UUID) -> dict[str, Any]:
    return await _command(job_id, "RESUME", TransferStatus.RUNNING, allowed={TransferStatus.PAUSED})


async def stop_job(job_id: UUID, *, restore: bool = True) -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        repo = TransferJobRepository(session)
        job = await repo.get(str(job_id))
        if job is None:
            raise KeyError(str(job_id))
        status = TransferStatus(job.status)
        if status in TERMINAL_STATUSES:
            return _job_to_dict(job)
        plan = dict(job.constraint_plan or {})
        plan["on_stop"] = "restore_now" if restore else "leave_disabled"
        job.constraint_plan = plan
        await session.commit()
        await repo.issue_command(str(job_id), "STOP")
        await repo.append_log(str(job_id), "Transfer stop requested — worker will halt after current chunk", level="warning")
        updated = await repo.set_status(str(job_id), TransferStatus.STOPPED.value, phase="done", set_completed=True)
    assert updated is not None
    return _job_to_dict(updated)


async def update_threshold(job_id: UUID, threshold: TransferThreshold) -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        repo = TransferJobRepository(session)
        job = await repo.get(str(job_id))
        if job is None:
            raise KeyError(str(job_id))
        status = TransferStatus(job.status)
        if status in TERMINAL_STATUSES or status in {TransferStatus.PREPARING, TransferStatus.RESTORING}:
            raise TransferError(f"Cannot change threshold while status is {status.value}")
        payload = threshold.model_dump()
        payload["chunk_size"] = threshold.clamped_chunk_size()
        await repo.update_threshold(str(job_id), payload)
        await repo.append_log(
            str(job_id),
            f"Threshold updated — chunk_size={payload['chunk_size']} "
            f"max_rows_per_sec={payload.get('max_rows_per_sec')}",
        )
        job = await repo.get(str(job_id))
    assert job is not None
    return _job_to_dict(job)


async def _command(
    job_id: UUID,
    command: str,
    next_status: TransferStatus,
    *,
    allowed: set[TransferStatus],
) -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        repo = TransferJobRepository(session)
        job = await repo.get(str(job_id))
        if job is None:
            raise KeyError(str(job_id))
        status = TransferStatus(job.status)
        if status not in allowed:
            raise TransferError(f"Cannot {command.lower()} job in status {status.value}")
        await repo.issue_command(str(job_id), command)
        await repo.append_log(str(job_id), f"Transfer {command.lower()} requested")
        updated = await repo.set_status(str(job_id), next_status.value)
    assert updated is not None
    return _job_to_dict(updated)


async def _overlapping_jobs(
    *,
    source_connection_id: str,
    target_connection_id: str,
    target_keys: set[str],
) -> list[dict[str, Any]]:
    async with AsyncSessionFactory() as session:
        jobs = await TransferJobRepository(session).find_overlapping(
            source_connection_id=source_connection_id,
            target_connection_id=target_connection_id,
            target_keys=target_keys,
            statuses={s.value for s in ACTIVE_STATUSES},
        )
    out = []
    for job in jobs:
        overlapping = [
            f"{p.target_schema}.{p.target_table}"
            for p in job.table_plans
            if f"{p.target_schema}.{p.target_table}".lower() in target_keys
        ]
        out.append({
            "job_id": job.transfer_job_id,
            "kind": "transfer",
            "status": job.status,
            "overlapping_tables": overlapping,
            "rows_copied": job.rows_copied,
            "message": f"{job.status.title()} transfer already covers {', '.join(overlapping)}",
        })
    return out
