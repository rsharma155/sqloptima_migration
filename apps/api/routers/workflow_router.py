# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""Temporal workflow submission and status-sync routes (L-9).

Routes:
  POST /api/v1/workflows/start   — submit a FullMigrationWorkflow to Temporal;
                                   returns a migration job ID trackable via
                                   GET /api/v1/migrations/{id}.
  POST /api/v1/workflows/{id}/sync   — poll Temporal and update job status.
  POST /api/v1/workflows/{id}/cancel — cancel a Temporal-controlled job.

All routes require OPERATOR or higher role.  The returned job IDs are normal
migration_jobs rows — callers use the existing migrations endpoints to track
progress.
"""

from __future__ import annotations

import os
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from apps.api.middleware.auth import UserRole, require_role
from infrastructure.metadata_db.session import AsyncSessionFactory
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/workflows", tags=["workflows"])


# ── Models ───────────────────────────────────────────────────────────────────

class WorkflowStartRequest(BaseModel):
    source_connection_id: str
    target_connection_id: str
    tables: list[str] = Field(default_factory=list)
    schemas: list[str] = Field(default_factory=lambda: ["dbo"])
    chunk_size: int = Field(default=10_000, ge=100, le=1_000_000)
    parallel_workers: int = Field(default=4, ge=1, le=32)
    validate_after_migration: bool = True


class WorkflowStartResponse(BaseModel):
    job_id: str
    workflow_handle_id: str
    message: str


class CutoverStartRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_connection_id: str
    target_connection_id: str
    tables: list[str] = Field(default_factory=list)
    schema_name: str = Field(default="dbo", alias="schema")
    target_schema: str = "public"
    require_human_approval: bool = True
    snapshot_ref: str | None = None


class CutoverSignalRequest(BaseModel):
    approved: bool = True
    reason: str = ""


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/start", response_model=WorkflowStartResponse)
async def start_workflow(
    req: WorkflowStartRequest,
    _: dict = require_role(UserRole.OPERATOR),
) -> WorkflowStartResponse:
    """Submit a FullMigrationWorkflow to Temporal.

    The job is tracked in the metadata DB — use
    ``GET /api/v1/migrations/{job_id}`` to poll progress.
    """
    from application.workflow_bridge_service import WorkflowBridgeService
    from infrastructure.temporal.client import TemporalClientFactory

    temporal_host = os.environ.get("TEMPORAL_HOST", "localhost")
    temporal_port = int(os.environ.get("TEMPORAL_PORT", "7233"))

    try:
        temporal_client = await TemporalClientFactory.create(
            host=temporal_host,
            port=temporal_port,
        )
    except Exception as exc:
        logger.error("temporal_connect_failed", error=str(exc))
        raise HTTPException(
            status_code=503,
            detail=f"Cannot connect to Temporal at {temporal_host}:{temporal_port}: {exc}",
        ) from exc

    svc = WorkflowBridgeService(
        session_factory=AsyncSessionFactory,
        temporal_client=temporal_client,
    )

    try:
        job_id = await svc.start_workflow(
            source_connection_id=req.source_connection_id,
            target_connection_id=req.target_connection_id,
            tables=req.tables,
            schemas=req.schemas,
            chunk_size=req.chunk_size,
            parallel_workers=req.parallel_workers,
            validate_after=req.validate_after_migration,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Reload the job to get the handle_id
    async with AsyncSessionFactory() as sess:
        from infrastructure.metadata_db.models import MigrationJobRecord
        job = await sess.get(MigrationJobRecord, job_id)
        handle_id = job.workflow_handle_id if job else ""

    logger.info("workflow_started_via_api", job_id=job_id, handle_id=handle_id)
    return WorkflowStartResponse(
        job_id=job_id,
        workflow_handle_id=handle_id or "",
        message=f"Workflow started. Track via GET /api/v1/migrations/{job_id}",
    )


@router.post("/{job_id}/sync", status_code=204, response_model=None)
async def sync_workflow_status(
    job_id: UUID,
    _: dict = require_role(UserRole.OPERATOR),
) -> None:
    """Poll Temporal and update the job row for a Temporal-controlled migration."""
    from application.workflow_bridge_service import WorkflowBridgeService
    from infrastructure.temporal.client import TemporalClientFactory

    temporal_host = os.environ.get("TEMPORAL_HOST", "localhost")
    temporal_port = int(os.environ.get("TEMPORAL_PORT", "7233"))

    try:
        temporal_client = await TemporalClientFactory.create(
            host=temporal_host, port=temporal_port
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Cannot connect to Temporal: {exc}") from exc

    svc = WorkflowBridgeService(
        session_factory=AsyncSessionFactory,
        temporal_client=temporal_client,
    )
    try:
        await svc.sync_status(str(job_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/cutover/start", response_model=WorkflowStartResponse)
async def start_cutover_workflow(
    req: CutoverStartRequest,
    _: dict = require_role(UserRole.OPERATOR),
) -> WorkflowStartResponse:
    """Submit a near-zero-downtime cutover workflow with human approval gate."""
    from application.workflow_bridge_service import WorkflowBridgeService
    from infrastructure.temporal.client import TemporalClientFactory

    temporal_host = os.environ.get("TEMPORAL_HOST", "localhost")
    temporal_port = int(os.environ.get("TEMPORAL_PORT", "7233"))
    try:
        temporal_client = await TemporalClientFactory.create(
            host=temporal_host, port=temporal_port,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Cannot connect to Temporal: {exc}") from exc

    svc = WorkflowBridgeService(session_factory=AsyncSessionFactory, temporal_client=temporal_client)
    try:
        job_id = await svc.start_cutover_workflow(
            source_connection_id=req.source_connection_id,
            target_connection_id=req.target_connection_id,
            tables=req.tables,
            schema=req.schema_name,
            target_schema=req.target_schema,
            require_human_approval=req.require_human_approval,
            snapshot_ref=req.snapshot_ref,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    async with AsyncSessionFactory() as sess:
        from infrastructure.metadata_db.models import MigrationJobRecord
        job = await sess.get(MigrationJobRecord, job_id)
        handle_id = job.workflow_handle_id if job else ""

    return WorkflowStartResponse(
        job_id=job_id,
        workflow_handle_id=handle_id or "",
        message=f"Cutover workflow started. Approve via POST /api/v1/workflows/cutover/{job_id}/approve",
    )


@router.post("/cutover/{job_id}/approve", status_code=204, response_model=None)
async def approve_cutover(
    job_id: UUID,
    _: dict = require_role(UserRole.OPERATOR),
) -> None:
    """Approve a pending cutover (sends Temporal approve_cutover signal)."""
    from application.workflow_bridge_service import WorkflowBridgeService
    from infrastructure.temporal.client import TemporalClientFactory

    temporal_client = await TemporalClientFactory.create()
    svc = WorkflowBridgeService(session_factory=AsyncSessionFactory, temporal_client=temporal_client)
    try:
        await svc.signal_cutover(str(job_id), approved=True)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/cutover/{job_id}/reject", status_code=204, response_model=None)
async def reject_cutover(
    job_id: UUID,
    req: CutoverSignalRequest,
    _: dict = require_role(UserRole.OPERATOR),
) -> None:
    """Reject a pending cutover and trigger rollback path."""
    from application.workflow_bridge_service import WorkflowBridgeService
    from infrastructure.temporal.client import TemporalClientFactory

    temporal_client = await TemporalClientFactory.create()
    svc = WorkflowBridgeService(session_factory=AsyncSessionFactory, temporal_client=temporal_client)
    try:
        await svc.signal_cutover(str(job_id), approved=False, reason=req.reason)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/cutover/{job_id}/connection-switch")
async def get_connection_switch_manifest(
    job_id: UUID,
    _: dict = require_role(UserRole.OPERATOR),
) -> dict:
    """Return the post-cutover connection switch manifest for operators."""
    from domains.orchestration.cutover_service import CutoverService

    async with AsyncSessionFactory() as session:
        record = await CutoverService(session).get_latest_checkpoint(str(job_id))
    if not record or not record.connection_switch:
        raise HTTPException(status_code=404, detail="Connection switch manifest not available")
    return record.connection_switch


@router.post("/cutover/{job_id}/rollback")
async def rollback_cutover(
    job_id: UUID,
    _: dict = require_role(UserRole.OPERATOR),
) -> dict:
    """Manually rollback a cutover within the rollback window."""
    from application.workflow_bridge_service import WorkflowBridgeService

    svc = WorkflowBridgeService(session_factory=AsyncSessionFactory, temporal_client=None)
    try:
        return await svc.rollback_cutover_job(str(job_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{job_id}/cancel", status_code=204, response_model=None)
async def cancel_workflow(
    job_id: UUID,
    _: dict = require_role(UserRole.OPERATOR),
) -> None:
    """Cancel a Temporal-controlled migration job."""
    from application.workflow_bridge_service import WorkflowBridgeService
    from infrastructure.temporal.client import TemporalClientFactory

    temporal_host = os.environ.get("TEMPORAL_HOST", "localhost")
    temporal_port = int(os.environ.get("TEMPORAL_PORT", "7233"))

    try:
        temporal_client = await TemporalClientFactory.create(
            host=temporal_host, port=temporal_port
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Cannot connect to Temporal: {exc}") from exc

    svc = WorkflowBridgeService(
        session_factory=AsyncSessionFactory,
        temporal_client=temporal_client,
    )
    try:
        await svc.cancel_workflow(str(job_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
