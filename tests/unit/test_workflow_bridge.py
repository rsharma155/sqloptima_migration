# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""TDD tests for application/workflow_bridge_service.py (L-9).

WorkflowBridgeService is the seam between the Temporal control plane and the
shared MigrationJobRecord in the metadata DB.  It lets the REST API display
progress for both REST-controlled and Temporal-controlled jobs via the same
GET /api/v1/migrations/{id} endpoint.

Contract:
  start_workflow:
  - Creates a MigrationJobRecord with status=PENDING and no workflow_handle_id.
  - Calls Temporal client.start_workflow with a FullMigrationWorkflowInput.
  - Persists the returned Temporal workflow ID as workflow_handle_id.
  - Returns the migration job ID.

  sync_status:
  - Describes the Temporal workflow execution.
  - Maps Temporal workflow status → MigrationJobRecord.status.
  - Updates completed_at when the workflow finishes.

  cancel_workflow:
  - Cancels the Temporal workflow execution.
  - Updates job status to STOPPED in the DB.

  resolve_connection:
  - Fetches ConnectionRecord from DB and decrypts the password.
  - Returns a dict suitable for SqlServerConnectionConfig / PostgresConnectionConfig.
  - Raises ValueError when connection_id is not found.

All Temporal client calls are mocked — no live Temporal server needed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from application.workflow_bridge_service import (
    WorkflowBridgeService,
    TemporalJobStatus,
    temporal_status_to_job_status,
)
from infrastructure.metadata_db.models import ConnectionRecord, MigrationJobRecord


# ── helpers ─────────────────────────────────────────────────────────────────

def _make_connection(db_type: str = "sqlserver") -> ConnectionRecord:
    return ConnectionRecord(
        project_connection_id=str(uuid4()),
        name="Test Connection",
        db_type=db_type,
        host="localhost",
        port=1433 if db_type == "sqlserver" else 5432,
        database_name="testdb",
        username="sa",
        encrypted_password="fake-encrypted-pw",
    )


def _make_job(workflow_handle_id: str | None = None) -> MigrationJobRecord:
    return MigrationJobRecord(
        migration_job_id=str(uuid4()),
        status="PENDING",
        workflow_handle_id=workflow_handle_id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


# ═══════════════════════════════════════════════════════════════════════════
# temporal_status_to_job_status mapping
# ═══════════════════════════════════════════════════════════════════════════

class TestStatusMapping:
    def test_running_maps_to_running(self):
        assert temporal_status_to_job_status(TemporalJobStatus.RUNNING) == "RUNNING"

    def test_completed_maps_to_completed(self):
        assert temporal_status_to_job_status(TemporalJobStatus.COMPLETED) == "COMPLETED"

    def test_failed_maps_to_failed(self):
        assert temporal_status_to_job_status(TemporalJobStatus.FAILED) == "FAILED"

    def test_cancelled_maps_to_stopped(self):
        assert temporal_status_to_job_status(TemporalJobStatus.CANCELLED) == "STOPPED"

    def test_terminated_maps_to_stopped(self):
        assert temporal_status_to_job_status(TemporalJobStatus.TERMINATED) == "STOPPED"

    def test_timed_out_maps_to_failed(self):
        assert temporal_status_to_job_status(TemporalJobStatus.TIMED_OUT) == "FAILED"

    def test_unknown_maps_to_running(self):
        assert temporal_status_to_job_status(TemporalJobStatus.UNKNOWN) == "RUNNING"


# ═══════════════════════════════════════════════════════════════════════════
# start_workflow
# ═══════════════════════════════════════════════════════════════════════════

class TestStartWorkflow:
    async def test_creates_job_record_and_transitions_to_running(self, test_session_factory):
        mock_temporal = AsyncMock()
        mock_temporal.start_workflow.return_value = "temporal-wf-id-123"

        src = _make_connection("sqlserver")
        tgt = _make_connection("postgresql")

        async with test_session_factory() as sess:
            sess.add(src)
            sess.add(tgt)
            await sess.commit()

        svc = WorkflowBridgeService(
            session_factory=test_session_factory,
            temporal_client=mock_temporal,
        )
        job_id = await svc.start_workflow(
            source_connection_id=src.project_connection_id,
            target_connection_id=tgt.project_connection_id,
            tables=["users", "orders"],
        )

        assert job_id is not None

        async with test_session_factory() as sess:
            job = await sess.get(MigrationJobRecord, job_id)
            assert job is not None
            # After successful Temporal submission, job transitions PENDING → RUNNING
            assert job.status == "RUNNING"
            assert job.started_at is not None

    async def test_persists_temporal_workflow_handle_id(self, test_session_factory):
        expected_handle = "temporal-workflow-abc123"
        mock_temporal = AsyncMock()
        mock_temporal.start_workflow.return_value = expected_handle

        src = _make_connection("sqlserver")
        tgt = _make_connection("postgresql")
        async with test_session_factory() as sess:
            sess.add(src)
            sess.add(tgt)
            await sess.commit()

        svc = WorkflowBridgeService(
            session_factory=test_session_factory,
            temporal_client=mock_temporal,
        )
        job_id = await svc.start_workflow(
            source_connection_id=src.project_connection_id,
            target_connection_id=tgt.project_connection_id,
            tables=["users"],
        )

        async with test_session_factory() as sess:
            job = await sess.get(MigrationJobRecord, job_id)
            assert job.workflow_handle_id == expected_handle

    async def test_temporal_start_is_called_with_connection_ids(self, test_session_factory):
        mock_temporal = AsyncMock()
        mock_temporal.start_workflow.return_value = "wf-id-456"

        src = _make_connection("sqlserver")
        tgt = _make_connection("postgresql")
        async with test_session_factory() as sess:
            sess.add(src)
            sess.add(tgt)
            await sess.commit()

        svc = WorkflowBridgeService(
            session_factory=test_session_factory,
            temporal_client=mock_temporal,
        )
        await svc.start_workflow(
            source_connection_id=src.project_connection_id,
            target_connection_id=tgt.project_connection_id,
            tables=["products"],
        )

        mock_temporal.start_workflow.assert_called_once()
        call_kwargs = mock_temporal.start_workflow.call_args
        # The workflow input must carry the connection IDs (not raw credentials)
        wf_input = call_kwargs.args[1] if call_kwargs.args else call_kwargs.kwargs.get("arg")
        assert wf_input is not None
        assert str(wf_input.source_connection_id) == src.project_connection_id
        assert str(wf_input.target_connection_id) == tgt.project_connection_id
        assert "products" in wf_input.tables

    async def test_raises_when_source_connection_not_found(self, test_session_factory):
        mock_temporal = AsyncMock()
        svc = WorkflowBridgeService(
            session_factory=test_session_factory,
            temporal_client=mock_temporal,
        )
        with pytest.raises(ValueError, match="Connection.*not found"):
            await svc.start_workflow(
                source_connection_id="nonexistent-id",
                target_connection_id="also-nonexistent",
                tables=["users"],
            )


# ═══════════════════════════════════════════════════════════════════════════
# sync_status
# ═══════════════════════════════════════════════════════════════════════════

class TestSyncStatus:
    async def test_syncs_running_status(self, test_session_factory):
        job = _make_job(workflow_handle_id="wf-running")
        async with test_session_factory() as sess:
            sess.add(job)
            await sess.commit()

        mock_temporal = AsyncMock()
        mock_temporal.describe_workflow.return_value = TemporalJobStatus.RUNNING

        svc = WorkflowBridgeService(
            session_factory=test_session_factory,
            temporal_client=mock_temporal,
        )
        await svc.sync_status(job.migration_job_id)

        async with test_session_factory() as sess:
            updated = await sess.get(MigrationJobRecord, job.migration_job_id)
            assert updated.status == "RUNNING"

    async def test_syncs_completed_status_and_sets_completed_at(self, test_session_factory):
        job = _make_job(workflow_handle_id="wf-done")
        async with test_session_factory() as sess:
            sess.add(job)
            await sess.commit()

        mock_temporal = AsyncMock()
        mock_temporal.describe_workflow.return_value = TemporalJobStatus.COMPLETED

        svc = WorkflowBridgeService(
            session_factory=test_session_factory,
            temporal_client=mock_temporal,
        )
        await svc.sync_status(job.migration_job_id)

        async with test_session_factory() as sess:
            updated = await sess.get(MigrationJobRecord, job.migration_job_id)
            assert updated.status == "COMPLETED"
            assert updated.completed_at is not None

    async def test_noop_for_job_without_workflow_handle(self, test_session_factory):
        job = _make_job(workflow_handle_id=None)
        async with test_session_factory() as sess:
            sess.add(job)
            await sess.commit()

        mock_temporal = AsyncMock()
        svc = WorkflowBridgeService(
            session_factory=test_session_factory,
            temporal_client=mock_temporal,
        )
        await svc.sync_status(job.migration_job_id)

        mock_temporal.describe_workflow.assert_not_called()

    async def test_raises_for_unknown_job_id(self, test_session_factory):
        mock_temporal = AsyncMock()
        svc = WorkflowBridgeService(
            session_factory=test_session_factory,
            temporal_client=mock_temporal,
        )
        with pytest.raises(ValueError, match="Job.*not found"):
            await svc.sync_status("nonexistent-job-id")


# ═══════════════════════════════════════════════════════════════════════════
# cancel_workflow
# ═══════════════════════════════════════════════════════════════════════════

class TestCancelWorkflow:
    async def test_cancels_temporal_and_sets_stopped_status(self, test_session_factory):
        job = _make_job(workflow_handle_id="wf-to-cancel")
        job.status = "RUNNING"
        async with test_session_factory() as sess:
            sess.add(job)
            await sess.commit()

        mock_temporal = AsyncMock()
        svc = WorkflowBridgeService(
            session_factory=test_session_factory,
            temporal_client=mock_temporal,
        )
        await svc.cancel_workflow(job.migration_job_id)

        mock_temporal.cancel_workflow.assert_called_once_with("wf-to-cancel")

        async with test_session_factory() as sess:
            updated = await sess.get(MigrationJobRecord, job.migration_job_id)
            assert updated.status == "STOPPED"

    async def test_noop_cancel_for_job_without_workflow_handle(self, test_session_factory):
        job = _make_job(workflow_handle_id=None)
        async with test_session_factory() as sess:
            sess.add(job)
            await sess.commit()

        mock_temporal = AsyncMock()
        svc = WorkflowBridgeService(
            session_factory=test_session_factory,
            temporal_client=mock_temporal,
        )
        await svc.cancel_workflow(job.migration_job_id)

        mock_temporal.cancel_workflow.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════
# resolve_connection
# ═══════════════════════════════════════════════════════════════════════════

class TestResolveConnection:
    async def test_returns_connection_config_dict(self, test_session_factory):
        conn = _make_connection("sqlserver")
        async with test_session_factory() as sess:
            sess.add(conn)
            await sess.commit()

        mock_sm = MagicMock()
        mock_sm.decrypt_auto.return_value = "decrypted-password"
        mock_temporal = AsyncMock()

        svc = WorkflowBridgeService(
            session_factory=test_session_factory,
            temporal_client=mock_temporal,
            secrets_manager=mock_sm,
        )
        config = await svc.resolve_connection(conn.project_connection_id)

        assert config["host"] == "localhost"
        assert config["database"] == "testdb"
        assert config["username"] == "sa"
        assert config["password"] == "decrypted-password"
        assert config["db_type"] == "sqlserver"

    async def test_resolve_connection_includes_ssl_flags(self, test_session_factory):
        conn = _make_connection("sqlserver")
        conn.ssl_enabled = True
        async with test_session_factory() as sess:
            sess.add(conn)
            await sess.commit()

        mock_sm = MagicMock()
        mock_sm.decrypt_auto.return_value = "decrypted-password"
        svc = WorkflowBridgeService(
            session_factory=test_session_factory,
            temporal_client=AsyncMock(),
            secrets_manager=mock_sm,
        )
        config = await svc.resolve_connection(conn.project_connection_id)
        assert config["ssl_enabled"] is True
        assert config["trust_server_certificate"] is True

    async def test_raises_when_connection_not_found(self, test_session_factory):
        mock_temporal = AsyncMock()
        svc = WorkflowBridgeService(
            session_factory=test_session_factory,
            temporal_client=mock_temporal,
        )
        with pytest.raises(ValueError, match="Connection.*not found"):
            await svc.resolve_connection("nonexistent")
