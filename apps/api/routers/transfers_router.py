"""
Module: transfers_router.py
Purpose: REST API for Cross-Database Transfer jobs.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

import application.transfer_service as svc
from apps.api.middleware.auth import UserRole, require_role
from domains.licensing.editions import require_feature
from domains.licensing.license_enforcement import require_valid_license
from domains.transfer.transfer_models import TransferTableMapping, TransferThreshold
from domains.transfer.transfer_path import TransferPath
from shared.tenancy.project_scope import resolve_project_filter

router = APIRouter(tags=["transfers"])


def _is_admin(user: dict) -> bool:
    return user.get("role") == UserRole.ADMIN.value


class TransferTableIn(BaseModel):
    source_schema: str
    source_table: str
    target_schema: str
    target_table: str
    columns: list[str] = Field(default_factory=list)


class TransferPreflightRequest(BaseModel):
    path: TransferPath
    source_connection_id: UUID
    target_connection_id: UUID
    tables: list[TransferTableIn]
    create_if_missing: bool = False
    clone_objects: bool = False


class TransferCreateRequest(TransferPreflightRequest):
    chunk_size: int = Field(default=10_000, ge=100, le=1_000_000)
    min_chunk_size: int = Field(default=1_000, ge=100, le=1_000_000)
    max_chunk_size: int = Field(default=100_000, ge=100, le=2_000_000)
    max_rows_per_sec: int | None = Field(default=None, ge=1)
    constraint_plan: dict[str, Any] | None = None
    project_id: str | None = None


class TransferStopRequest(BaseModel):
    restore: bool = True


class TransferThresholdRequest(BaseModel):
    chunk_size: int = Field(ge=100, le=1_000_000)
    min_chunk_size: int = Field(default=1_000, ge=100, le=1_000_000)
    max_chunk_size: int = Field(default=100_000, ge=100, le=2_000_000)
    max_rows_per_sec: int | None = Field(default=None, ge=1)


def _mappings(tables: list[TransferTableIn]) -> list[TransferTableMapping]:
    return [TransferTableMapping.model_validate(t.model_dump()) for t in tables]


def _raise(exc: Exception) -> None:
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, KeyError):
        raise HTTPException(status_code=404, detail="Transfer job not found") from exc
    if isinstance(exc, svc.TransferError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/transfers/catalog/schemas")
async def transfer_catalog_schemas(
    connection_id: UUID,
    _: dict = require_role(UserRole.VIEWER),
):
    require_feature("transfer")
    try:
        schemas = await svc.catalog_schemas(connection_id)
        return {"schemas": schemas}
    except Exception as exc:
        _raise(exc)


@router.get("/transfers/catalog/tables")
async def transfer_catalog_tables(
    connection_id: UUID,
    schema: str,
    _: dict = require_role(UserRole.VIEWER),
):
    require_feature("transfer")
    try:
        tables = await svc.catalog_tables(connection_id, schema)
        return {"tables": tables}
    except Exception as exc:
        _raise(exc)


@router.post("/transfers/preflight")
async def transfer_preflight(req: TransferPreflightRequest, _: dict = require_role(UserRole.OPERATOR)):
    require_valid_license()
    require_feature("transfer")
    try:
        return await svc.run_preflight(
            path=req.path,
            source_connection_id=req.source_connection_id,
            target_connection_id=req.target_connection_id,
            tables=_mappings(req.tables),
            create_if_missing=req.create_if_missing,
            clone_objects=req.clone_objects,
        )
    except Exception as exc:
        _raise(exc)


@router.get("/transfers")
async def list_transfers(
    project_id: str | None = Query(default=None),
    user: dict = require_role(UserRole.VIEWER),
):
    require_feature("transfer")
    scope = resolve_project_filter(
        project_id,
        user_project_id=user.get("project_id"),
        is_admin=_is_admin(user),
    )
    return await svc.list_jobs(project_id=scope)


@router.post("/transfers")
async def create_transfer(req: TransferCreateRequest, user: dict = require_role(UserRole.OPERATOR)):
    require_valid_license()
    require_feature("transfer")
    try:
        return await svc.create_job(
            path=req.path,
            source_connection_id=req.source_connection_id,
            target_connection_id=req.target_connection_id,
            tables=_mappings(req.tables),
            threshold=TransferThreshold(
                chunk_size=req.chunk_size,
                min_chunk_size=req.min_chunk_size,
                max_chunk_size=req.max_chunk_size,
                max_rows_per_sec=req.max_rows_per_sec,
            ),
            constraint_plan=req.constraint_plan,
            create_if_missing=req.create_if_missing,
            clone_objects=req.clone_objects,
            project_id=req.project_id or user.get("project_id"),
        )
    except Exception as exc:
        _raise(exc)


@router.get("/transfers/{job_id}")
async def get_transfer(job_id: UUID, user: dict = require_role(UserRole.VIEWER)):
    require_feature("transfer")
    try:
        return await svc.get_job(
            job_id,
            user_project_id=user.get("project_id"),
            is_admin=_is_admin(user),
        )
    except Exception as exc:
        _raise(exc)


@router.get("/transfers/{job_id}/progress")
async def transfer_progress(job_id: UUID, user: dict = require_role(UserRole.VIEWER)):
    require_feature("transfer")
    try:
        job = await svc.get_job(
            job_id,
            user_project_id=user.get("project_id"),
            is_admin=_is_admin(user),
        )
        return {
            "job_id": job["job_id"],
            "status": job["status"],
            "phase": job["phase"],
            "overall_percentage": job["overall_percentage"],
            "total_rows_copied": job["rows_copied"],
            "total_rows_estimate": job["rows_total"],
            "effective_chunk_size": job["threshold"]["chunk_size"],
            "tables": {
                f"{t['source_schema']}.{t['source_table']}": {
                    "status": t["status"],
                    "rows_copied": t["rows_copied"],
                    "row_count_estimate": t["row_count_estimate"],
                    "percent": (
                        min(100.0, round(100.0 * t["rows_copied"] / t["row_count_estimate"], 1))
                        if t["row_count_estimate"]
                        else 0.0
                    ),
                    "error": t.get("error"),
                    "error_count": t.get("error_count") or 0,
                }
                for t in job["tables"]
            },
        }
    except Exception as exc:
        _raise(exc)


@router.get("/transfers/{job_id}/metrics")
async def transfer_metrics(job_id: UUID, user: dict = require_role(UserRole.VIEWER)):
    require_feature("transfer")
    try:
        return await svc.get_live_metrics(
            job_id,
            user_project_id=user.get("project_id"),
            is_admin=_is_admin(user),
        )
    except Exception as exc:
        _raise(exc)


@router.get("/transfers/{job_id}/logs")
async def transfer_logs(
    job_id: UUID,
    after_id: int = 0,
    limit: int = 200,
    table_name: str | None = Query(default=None),
    user: dict = require_role(UserRole.VIEWER),
):
    require_feature("transfer")
    try:
        await svc.get_job(job_id, user_project_id=user.get("project_id"), is_admin=_is_admin(user))
        return await svc.list_logs(job_id, after_id=after_id, limit=limit, table_name=table_name)
    except Exception as exc:
        _raise(exc)


@router.post("/transfers/{job_id}/pause")
async def pause_transfer(job_id: UUID, _: dict = require_role(UserRole.OPERATOR)):
    require_feature("transfer")
    try:
        return await svc.pause_job(job_id)
    except Exception as exc:
        _raise(exc)


@router.post("/transfers/{job_id}/resume")
async def resume_transfer(job_id: UUID, _: dict = require_role(UserRole.OPERATOR)):
    require_feature("transfer")
    try:
        return await svc.resume_job(job_id)
    except Exception as exc:
        _raise(exc)


@router.post("/transfers/{job_id}/stop")
async def stop_transfer(
    job_id: UUID,
    req: TransferStopRequest | None = None,
    _: dict = require_role(UserRole.OPERATOR),
):
    require_feature("transfer")
    try:
        restore = True if req is None else req.restore
        return await svc.stop_job(job_id, restore=restore)
    except Exception as exc:
        _raise(exc)


@router.patch("/transfers/{job_id}/threshold")
async def patch_threshold(
    job_id: UUID,
    req: TransferThresholdRequest,
    _: dict = require_role(UserRole.OPERATOR),
):
    require_feature("transfer")
    try:
        return await svc.update_threshold(job_id, TransferThreshold.model_validate(req.model_dump()))
    except Exception as exc:
        _raise(exc)
