"""
Module: replication_router.py
Purpose: REST API for CDC replication stream lifecycle
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
# ruff: noqa: B008, E501

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import application.replication_service as repl_svc
from apps.api.middleware.auth import UserRole, require_role

router = APIRouter(tags=["replication"])


def _http_error_from_replication(exc: Exception, *, conn_type: str = "source") -> HTTPException:
    """Map replication failures to API errors with plain-language detail."""
    from shared.errors.error_catalog import format_connection_error

    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(
        status_code=502,
        detail=format_connection_error(str(exc), conn_type=conn_type),
    )


class CreateReplicationStreamRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    source_connection_id: str
    target_connection_id: str
    tables: list[str] = Field(min_length=1)
    source_schema: str = "dbo"
    target_schema: str = "public"
    mode: str = "cdc"


class UpdateReplicationStreamRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    source_connection_id: str | None = None
    target_connection_id: str | None = None
    tables: list[str] | None = Field(default=None, min_length=1)
    source_schema: str | None = None
    target_schema: str | None = None


class ReplicationStreamResponse(BaseModel):
    stream_id: str
    name: str
    status: str
    source_connection_id: str | None = None
    target_connection_id: str | None = None
    source_schema: str = "dbo"
    target_schema: str = "public"
    tables: list[Any] = Field(default_factory=list)
    concerns: list[Any] = Field(default_factory=list)
    events_captured: int = 0
    events_applied: int = 0
    queue_depth: int | None = None
    state: str | None = None
    error_message: str | None = None
    last_checkpoint_lsn: str | None = None


@router.get("/replication/target-status")
async def target_migration_status(
    target_connection_id: str,
    target_schema: str = "public",
    source_schema: str = "dbo",
    tables: str = "",
    user: dict = require_role(UserRole.VIEWER),
) -> list[dict[str, Any]]:
    _ = user
    table_list = [t.strip() for t in tables.split(",") if t.strip()]
    if not table_list:
        raise HTTPException(status_code=422, detail="tables query parameter is required")
    try:
        return await repl_svc.check_target_migration_status(
            target_connection_id=target_connection_id,
            target_schema=target_schema,
            tables=table_list,
            source_schema=source_schema,
        )
    except Exception as exc:
        raise _http_error_from_replication(exc, conn_type="target") from exc


@router.get("/replication/cdc-status")
async def cdc_status(
    source_connection_id: str,
    source_schema: str = "dbo",
    tables: str = "",
    user: dict = require_role(UserRole.VIEWER),
) -> dict[str, Any]:
    _ = user
    table_list = [t.strip() for t in tables.split(",") if t.strip()] if tables else None
    try:
        return await repl_svc.get_cdc_status(
            source_connection_id,
            source_schema,
            table_list,
        )
    except Exception as exc:
        raise _http_error_from_replication(exc, conn_type="source") from exc


@router.get("/replication/summary")
async def replication_summary(user: dict = require_role(UserRole.VIEWER)) -> dict[str, Any]:
    _ = user
    return await repl_svc.get_replication_summary()


@router.get("/replication/streams")
async def list_streams(user: dict = require_role(UserRole.VIEWER)) -> list[dict[str, Any]]:
    _ = user
    return await repl_svc.list_streams()


@router.get("/replication/streams/{stream_id}")
async def get_stream(stream_id: str, user: dict = require_role(UserRole.VIEWER)) -> dict[str, Any]:
    _ = user
    row = await repl_svc.get_stream(stream_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Stream {stream_id} not found")
    return row


@router.post("/replication/streams", status_code=201)
async def create_stream(
    req: CreateReplicationStreamRequest,
    user: dict = require_role(UserRole.OPERATOR),
) -> dict[str, Any]:
    _ = user
    try:
        return await repl_svc.create_stream(
            name=req.name,
            source_connection_id=req.source_connection_id,
            target_connection_id=req.target_connection_id,
            tables=req.tables,
            source_schema=req.source_schema,
            target_schema=req.target_schema,
            mode=req.mode,
        )
    except Exception as exc:
        raise _http_error_from_replication(exc, conn_type="source") from exc


@router.patch("/replication/streams/{stream_id}")
async def update_stream(
    stream_id: str,
    req: UpdateReplicationStreamRequest,
    user: dict = require_role(UserRole.OPERATOR),
) -> dict[str, Any]:
    _ = user
    try:
        return await repl_svc.update_stream(
            stream_id,
            name=req.name,
            source_connection_id=req.source_connection_id,
            target_connection_id=req.target_connection_id,
            tables=req.tables,
            source_schema=req.source_schema,
            target_schema=req.target_schema,
        )
    except Exception as exc:
        raise _http_error_from_replication(exc, conn_type="source") from exc


@router.delete("/replication/streams/{stream_id}")
async def delete_stream(stream_id: str, user: dict = require_role(UserRole.OPERATOR)) -> dict[str, bool]:
    _ = user
    deleted = await repl_svc.delete_stream(stream_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Stream {stream_id} not found")
    return {"deleted": True}


@router.post("/replication/streams/{stream_id}/start")
async def start_stream(stream_id: str, user: dict = require_role(UserRole.OPERATOR)) -> dict[str, Any]:
    _ = user
    try:
        return await repl_svc.start_stream(stream_id)
    except Exception as exc:
        raise _http_error_from_replication(exc, conn_type="source") from exc


@router.post("/replication/streams/{stream_id}/stop")
async def stop_stream(stream_id: str, user: dict = require_role(UserRole.OPERATOR)) -> dict[str, Any]:
    _ = user
    try:
        return await repl_svc.stop_stream(stream_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/replication/streams/{stream_id}/pause")
async def pause_stream(stream_id: str, user: dict = require_role(UserRole.OPERATOR)) -> dict[str, Any]:
    _ = user
    try:
        return await repl_svc.pause_stream(stream_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/replication/streams/{stream_id}/resume")
async def resume_stream(stream_id: str, user: dict = require_role(UserRole.OPERATOR)) -> dict[str, Any]:
    _ = user
    try:
        return await repl_svc.resume_stream(stream_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/replication/streams/{stream_id}/refresh-concerns")
async def refresh_stream_concerns(
    stream_id: str,
    user: dict = require_role(UserRole.OPERATOR),
) -> dict[str, Any]:
    _ = user
    try:
        concerns = await repl_svc.refresh_stream_concerns(stream_id)
        row = await repl_svc.get_stream(stream_id)
        return {"concerns": concerns, "stream": row}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/replication/streams/{stream_id}/details")
async def stream_details(stream_id: str, user: dict = require_role(UserRole.VIEWER)) -> dict[str, Any]:
    _ = user
    await repl_svc.refresh_stream_metrics(stream_id)
    row = await repl_svc.get_stream_details(stream_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Stream {stream_id} not found")
    return row


@router.get("/replication/streams/{stream_id}/status")
async def stream_status(stream_id: str, user: dict = require_role(UserRole.VIEWER)) -> dict[str, Any]:
    _ = user
    row = await repl_svc.get_stream(stream_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Stream {stream_id} not found")
    await repl_svc.refresh_stream_metrics(stream_id)
    return await repl_svc.get_stream(stream_id) or row
