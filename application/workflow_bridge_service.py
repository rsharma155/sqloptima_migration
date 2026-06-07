# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""WorkflowBridgeService — seam between Temporal and the shared metadata DB (L-9).

Domain:  Application
Module:  application.workflow_bridge_service

Architectural decision (L-9):
  Both the REST API and Temporal coexist as complementary control planes:

  REST API  ── interactive migrations: real-time pause/resume/stop,
                single-table jobs, progress polling from /api/v1/migrations.

  Temporal  ── durable long-running workflows: full multi-schema migration
                (discover → convert → migrate → validate), CDC cutover with
                human approval gate, periodic validation schedules.

  Bridge:
    Both planes write to the same ``migration_jobs`` table in the metadata DB.
    ``workflow_handle_id IS NULL``  → REST-controlled job (asyncio task).
    ``workflow_handle_id IS NOT NULL`` → Temporal-controlled job.
    GET /api/v1/migrations/{id} works for both transparently.

WorkflowBridgeService responsibilities:
  1. start_workflow  — create a MigrationJobRecord, submit to Temporal,
                       store the Temporal workflow execution ID.
  2. sync_status     — describe the Temporal execution and update the job row.
  3. cancel_workflow — cancel the Temporal execution and mark job STOPPED.
  4. resolve_connection — fetch a ConnectionRecord and decrypt its password,
                          returning a plain dict for activity configuration.

The Temporal client is injected so this service is fully testable without a
live Temporal server.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.metadata_db.models import ConnectionRecord, MigrationJobRecord
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


# ── Temporal status enum (mirrors temporalio WorkflowExecutionStatus) ────────

class TemporalJobStatus(str, Enum):
    """Simplified view of Temporal workflow execution status."""

    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TERMINATED = "TERMINATED"
    TIMED_OUT = "TIMED_OUT"
    UNKNOWN = "UNKNOWN"


def temporal_status_to_job_status(temporal_status: TemporalJobStatus) -> str:
    """Map a Temporal workflow status to a MigrationJobRecord status string."""
    _MAP = {
        TemporalJobStatus.RUNNING: "RUNNING",
        TemporalJobStatus.COMPLETED: "COMPLETED",
        TemporalJobStatus.FAILED: "FAILED",
        TemporalJobStatus.CANCELLED: "STOPPED",
        TemporalJobStatus.TERMINATED: "STOPPED",
        TemporalJobStatus.TIMED_OUT: "FAILED",
        TemporalJobStatus.UNKNOWN: "RUNNING",
    }
    return _MAP.get(temporal_status, "RUNNING")


# ── Workflow input dataclass ──────────────────────────────────────────────────

@dataclass
class FullMigrationWorkflowInput:
    """Input passed to Temporal's FullMigrationWorkflow.

    Uses connection_id references (not raw credentials) — activities resolve
    them at execution time via WorkflowBridgeService.resolve_connection().
    """

    job_id: str = field(default_factory=lambda: str(uuid4()))
    source_connection_id: str = ""
    target_connection_id: str = ""
    schemas: list[str] = field(default_factory=lambda: ["dbo"])
    tables: list[str] = field(default_factory=list)
    chunk_size: int = 10_000
    parallel_workers: int = 4
    validate_after_migration: bool = True
    notify_on_completion: bool = False
    notification_channels: list[str] = field(default_factory=list)


# ── TemporalClientAdapter — thin wrapper so the real client is swappable ─────

class TemporalClientAdapter:
    """Thin async wrapper around the real Temporal client.

    In tests this is replaced by a mock.  In production, pass the
    ``TemporalClient`` from ``infrastructure.temporal.client``.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    async def start_workflow(self, workflow_type: Any, arg: Any, workflow_id: str, task_queue: str) -> str:
        """Start a workflow execution and return its workflow execution ID."""
        handle = await self._client.start_workflow(
            workflow_type,
            arg,
            id=workflow_id,
            task_queue=task_queue,
        )
        return handle.id if hasattr(handle, "id") else workflow_id

    async def describe_workflow(self, workflow_id: str) -> TemporalJobStatus:
        """Return the current status of a workflow execution."""
        try:
            handle = self._client.get_workflow_handle(workflow_id)
            desc = await handle.describe()
            # Map temporalio enum names to our TemporalJobStatus
            raw = str(desc.status.name).upper() if hasattr(desc, "status") else "UNKNOWN"
            return TemporalJobStatus(raw) if raw in TemporalJobStatus._value2member_map_ else TemporalJobStatus.UNKNOWN
        except Exception as exc:
            logger.warning("workflow_describe_failed", workflow_id=workflow_id, error=str(exc))
            return TemporalJobStatus.UNKNOWN

    async def cancel_workflow(self, workflow_id: str) -> None:
        """Request cancellation of a workflow execution."""
        try:
            handle = self._client.get_workflow_handle(workflow_id)
            await handle.cancel()
        except Exception as exc:
            logger.warning("workflow_cancel_failed", workflow_id=workflow_id, error=str(exc))


# ── WorkflowBridgeService ─────────────────────────────────────────────────────

class WorkflowBridgeService:
    """Bridge between Temporal workflow executions and migration_jobs DB rows.

    Accepts either a raw Temporal client (production) or a mock adapter (tests).
    """

    TASK_QUEUE = os.environ.get("TEMPORAL_TASK_QUEUE", "migration-platform")

    def __init__(
        self,
        session_factory: Any,
        temporal_client: Any,
        secrets_manager: Any = None,
    ) -> None:
        self._session_factory = session_factory
        # Accepts either:
        #   - An AsyncMock / duck-typed object with start_workflow / describe_workflow
        #     / cancel_workflow methods — used in tests.
        #   - A TemporalClientAdapter wrapping the real temporalio client — used in prod.
        self._temporal = temporal_client
        self._sm = secrets_manager  # optional; injected for testing

    # ── Internal helpers ──────────────────────────────────────────────────

    def _get_secrets_manager(self) -> Any:
        if self._sm is not None:
            return self._sm
        from apps.api.dependencies import get_secrets
        return get_secrets()

    # ── Public API ────────────────────────────────────────────────────────

    async def start_workflow(
        self,
        source_connection_id: str,
        target_connection_id: str,
        tables: list[str],
        schemas: list[str] | None = None,
        chunk_size: int = 10_000,
        parallel_workers: int = 4,
        validate_after: bool = True,
        workflow_class: Any = None,
    ) -> str:
        """Create a MigrationJobRecord and submit it to Temporal.

        Returns the migration job ID (UUID string).  The caller can use this
        to poll ``GET /api/v1/migrations/{id}`` just like any REST-controlled job.

        Raises:
            ValueError: If either connection_id is not found in the DB.
        """
        async with self._session_factory() as sess:
            await self._assert_connection_exists(sess, source_connection_id, "source")
            await self._assert_connection_exists(sess, target_connection_id, "target")

        job_id = str(uuid4())
        wf_input = FullMigrationWorkflowInput(
            job_id=job_id,
            source_connection_id=source_connection_id,
            target_connection_id=target_connection_id,
            schemas=schemas or ["dbo"],
            tables=tables,
            chunk_size=chunk_size,
            parallel_workers=parallel_workers,
            validate_after_migration=validate_after,
        )

        # Persist job row (PENDING, no handle yet)
        async with self._session_factory() as sess:
            job = MigrationJobRecord(
                migration_job_id=job_id,
                source_project_connection_id=source_connection_id,
                target_project_connection_id=target_connection_id,
                status="PENDING",
                tables_total=len(tables),
                config={
                    "orchestration": "temporal",
                    "chunk_size": chunk_size,
                    "parallel_workers": parallel_workers,
                    "tables": tables,
                    "schemas": schemas or ["dbo"],
                },
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            sess.add(job)
            await sess.commit()

        # Submit to Temporal
        wf_id = f"migration-{job_id}"
        try:
            if workflow_class is None:
                try:
                    from domains.orchestration.workflows import FullMigrationWorkflow as workflow_class  # noqa: N806
                except ImportError:
                    workflow_class = "FullMigrationWorkflow"  # Temporal will resolve by name
            result = await self._temporal.start_workflow(
                workflow_class,
                wf_input,
                workflow_id=wf_id,
                task_queue=self.TASK_QUEUE,
            )
            # Real Temporal client returns a WorkflowHandle with .id; mocks return a string.
            handle_id: str = result.id if hasattr(result, "id") else (result or wf_id)
        except Exception as exc:
            # Mark job as FAILED if Temporal submission fails
            async with self._session_factory() as sess:
                job_row = await sess.get(MigrationJobRecord, job_id)
                if job_row:
                    job_row.status = "FAILED"
                    job_row.error = f"Temporal submission failed: {exc}"
                    await sess.commit()
            logger.error("temporal_start_workflow_failed", job_id=job_id, error=str(exc))
            raise

        # Update job row with the Temporal handle ID
        async with self._session_factory() as sess:
            job_row = await sess.get(MigrationJobRecord, job_id)
            if job_row:
                job_row.workflow_handle_id = handle_id
                job_row.status = "RUNNING"
                job_row.started_at = datetime.now(UTC)
                await sess.commit()

        logger.info("temporal_workflow_started", job_id=job_id, workflow_handle_id=handle_id)
        return job_id

    async def sync_status(self, job_id: str) -> None:
        """Poll Temporal and update the migration_jobs row for a Temporal-controlled job.

        No-op if the job has no ``workflow_handle_id`` (REST-controlled).

        Raises:
            ValueError: If job_id is not found.
        """
        async with self._session_factory() as sess:
            job = await sess.get(MigrationJobRecord, job_id)
            if job is None:
                raise ValueError(f"Job '{job_id}' not found")
            if not job.workflow_handle_id:
                return  # REST-controlled job — nothing to sync

            temporal_status = await self._temporal.describe_workflow(job.workflow_handle_id)
            new_status = temporal_status_to_job_status(temporal_status)
            job.status = new_status
            if new_status in ("COMPLETED", "FAILED", "STOPPED") and job.completed_at is None:
                job.completed_at = datetime.now(UTC)
            await sess.commit()

        logger.info("job_status_synced", job_id=job_id, status=new_status)

    async def cancel_workflow(self, job_id: str) -> None:
        """Cancel a Temporal-controlled migration and mark it STOPPED.

        No-op if the job has no ``workflow_handle_id``.

        Raises:
            ValueError: If job_id is not found.
        """
        async with self._session_factory() as sess:
            job = await sess.get(MigrationJobRecord, job_id)
            if job is None:
                raise ValueError(f"Job '{job_id}' not found")
            if not job.workflow_handle_id:
                return

            await self._temporal.cancel_workflow(job.workflow_handle_id)
            job.status = "STOPPED"
            job.completed_at = datetime.now(UTC)
            await sess.commit()

        logger.info("temporal_workflow_cancelled", job_id=job_id)

    async def start_cutover_workflow(
        self,
        source_connection_id: str,
        target_connection_id: str,
        tables: list[str],
        *,
        schema: str = "dbo",
        target_schema: str = "public",
        require_human_approval: bool = True,
        snapshot_ref: str | None = None,
    ) -> str:
        """Submit a CutoverWorkflow to Temporal and return the job ID."""
        from domains.orchestration.workflows import CutoverWorkflow, CutoverWorkflowInput

        async with self._session_factory() as sess:
            await self._assert_connection_exists(sess, source_connection_id, "source")
            await self._assert_connection_exists(sess, target_connection_id, "target")

        job_id = str(uuid4())
        wf_input = CutoverWorkflowInput(
            job_id=UUID(job_id),
            source_connection_id=source_connection_id,
            target_connection_id=target_connection_id,
            tables=tables,
            schema=schema,
            target_schema=target_schema,
            require_human_approval=require_human_approval,
            snapshot_ref=snapshot_ref,
        )

        async with self._session_factory() as sess:
            job = MigrationJobRecord(
                migration_job_id=job_id,
                source_project_connection_id=source_connection_id,
                target_project_connection_id=target_connection_id,
                status="PENDING",
                tables_total=len(tables),
                config={
                    "orchestration": "temporal",
                    "workflow_type": "cutover",
                    "tables": tables,
                    "schema": schema,
                    "target_schema": target_schema,
                },
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            sess.add(job)
            await sess.commit()

        wf_id = f"cutover-{job_id}"
        result = await self._temporal.start_workflow(
            CutoverWorkflow,
            wf_input,
            workflow_id=wf_id,
            task_queue=self.TASK_QUEUE,
        )
        handle_id: str = result.id if hasattr(result, "id") else (result or wf_id)

        async with self._session_factory() as sess:
            job_row = await sess.get(MigrationJobRecord, job_id)
            if job_row:
                job_row.workflow_handle_id = handle_id
                job_row.status = "RUNNING"
                job_row.started_at = datetime.now(UTC)
                await sess.commit()

        logger.info("cutover_workflow_started", job_id=job_id, handle_id=handle_id)
        return job_id

    async def signal_cutover(self, job_id: str, approved: bool, reason: str = "") -> None:
        """Send approve/reject signal to a running CutoverWorkflow."""
        async with self._session_factory() as sess:
            job = await sess.get(MigrationJobRecord, job_id)
            if job is None or not job.workflow_handle_id:
                raise ValueError(f"Cutover job '{job_id}' not found or not Temporal-controlled")

        handle = self._temporal._client.get_workflow_handle(job.workflow_handle_id)
        if approved:
            await handle.signal("approve_cutover")
        else:
            await handle.signal("reject_cutover", reason)

    async def rollback_cutover_job(self, job_id: str) -> dict:
        """Manually trigger cutover rollback for a job."""
        from domains.orchestration.activities import _resolve_postgres_connector
        from domains.orchestration.cutover_service import CutoverService

        async with self._session_factory() as sess:
            job = await sess.get(MigrationJobRecord, job_id)
            if job is None:
                raise ValueError(f"Job '{job_id}' not found")
            target_id = job.target_project_connection_id or ""

        target = None
        if target_id:
            target = await _resolve_postgres_connector(target_id)
        try:
            async with self._session_factory() as sess:
                svc = CutoverService(sess, target_connector=target)
                return await svc.rollback(job_id)
        finally:
            if target is not None:
                await target.disconnect()

    async def resolve_connection(self, connection_id: str) -> dict[str, Any]:
        """Fetch a ConnectionRecord and decrypt its password.

        Returns a plain dict with keys: host, port, database, username, password, db_type.
        Used by Temporal activities to build connector configs from connection_id references.

        Raises:
            ValueError: If connection_id is not found in the DB.
        """
        async with self._session_factory() as sess:
            result = await sess.execute(
                select(ConnectionRecord).where(ConnectionRecord.project_connection_id == connection_id)
            )
            conn = result.scalar_one_or_none()
            if conn is None:
                raise ValueError(f"Connection '{connection_id}' not found")

            sm = self._get_secrets_manager()
            password = ""
            if conn.encrypted_password and sm:
                try:
                    password = sm.decrypt_auto(conn.encrypted_password)
                except Exception:
                    password = conn.encrypted_password  # fallback for unencrypted

            return {
                "host": conn.host,
                "port": conn.port,
                "database": conn.database_name,
                "username": conn.username,
                "password": password,
                "db_type": conn.db_type,
                "ssl_enabled": bool(conn.ssl_enabled),
                "trust_server_certificate": bool(conn.ssl_enabled),
            }

    # ── Private ──────────────────────────────────────────────────────────

    async def _assert_connection_exists(
        self, sess: AsyncSession, connection_id: str, label: str
    ) -> None:
        result = await sess.execute(
            select(ConnectionRecord).where(ConnectionRecord.project_connection_id == connection_id)
        )
        if result.scalar_one_or_none() is None:
            raise ValueError(f"Connection '{connection_id}' not found ({label})")
