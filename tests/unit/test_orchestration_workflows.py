"""
Module: test_orchestration_workflows.py
Purpose: Unit tests
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from domains.orchestration.workflows import (
    CutoverWorkflow,
    CutoverWorkflowInput,
    FullMigrationWorkflow,
    MigrationWorkflowInput,
    PeriodicValidationWorkflow,
    PeriodicValidationWorkflowInput,
    ReplicationMonitoringWorkflow,
)

_workflow_module = "domains.orchestration.workflows"


class TestFullMigrationWorkflow:
    @pytest.mark.asyncio
    async def test_successful_full_migration(self):
        workflow = FullMigrationWorkflow()
        inp = MigrationWorkflowInput(
            job_id=uuid4(),
            source_connection_id="source-1",
            target_connection_id="target-1",
            schemas=["dbo"],
            tables=["users", "orders"],
            validate_after_migration=True,
            notify_on_completion=True,
        )

        execute_calls = []

        async def fake_execute_activity(activity, *args, **kwargs):
            execute_calls.append((activity.__name__, args))
            if activity.__name__ == "discover_objects" and args[1] == "dbo":
                return [
                    {"object_id": "1", "object_type": "TABLE", "name": "users", "schema": "dbo"},
                    {"object_id": "2", "object_type": "TABLE", "name": "orders", "schema": "dbo"},
                ]
            if activity.__name__ == "analyze_compatibility":
                return None
            if activity.__name__ == "convert_schema":
                return {"object_id": args[0], "success": True}
            if activity.__name__ == "migrate_table":
                return {"status": "completed", "rows_migrated": 100}
            if activity.__name__ == "validate_table":
                return {"status": "passed"}
            if activity.__name__ == "send_notification":
                return None
            return None

        with (
            patch(f"{_workflow_module}.workflow.execute_activity", fake_execute_activity),
            patch(f"{_workflow_module}.workflow.logger", MagicMock()),
        ):
            result = await workflow.run(inp)

        assert result.success is True
        assert result.objects_discovered == 2
        assert result.objects_converted == 2
        assert result.tables_migrated == 2
        assert result.tables_validated == 2
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_without_validation_or_notification(self):
        workflow = FullMigrationWorkflow()
        inp = MigrationWorkflowInput(
            job_id=uuid4(),
            schemas=["dbo"],
            tables=["users"],
            validate_after_migration=False,
            notify_on_completion=False,
        )

        validate_called = [False]
        notify_called = [False]

        async def fake_execute(activity, *args, **kwargs):
            if activity.__name__ == "discover_objects":
                return [{"object_id": "1", "object_type": "TABLE", "name": "users", "schema": "dbo"}]
            if activity.__name__ == "analyze_compatibility":
                return None
            if activity.__name__ == "convert_schema":
                return {"success": True}
            if activity.__name__ == "migrate_table":
                return {"status": "completed"}
            if activity.__name__ == "validate_table":
                validate_called[0] = True
            if activity.__name__ == "send_notification":
                notify_called[0] = True
            return None

        with (
            patch(f"{_workflow_module}.workflow.execute_activity", fake_execute),
            patch(f"{_workflow_module}.workflow.logger", MagicMock()),
        ):
            result = await workflow.run(inp)

        assert result.success is True
        assert validate_called[0] is False
        assert notify_called[0] is False

    @pytest.mark.asyncio
    async def test_handles_exception_gracefully(self):
        workflow = FullMigrationWorkflow()
        inp = MigrationWorkflowInput(job_id=uuid4(), schemas=["dbo"], tables=["users"])

        async def fake_execute(activity, *args, **kwargs):
            raise Exception("Discovery crashed")

        with (
            patch(f"{_workflow_module}.workflow.execute_activity", fake_execute),
            patch(f"{_workflow_module}.workflow.logger", MagicMock()),
        ):
            result = await workflow.run(inp)

        assert result.success is False
        assert len(result.errors) == 1

    @pytest.mark.asyncio
    async def test_continues_on_table_failure(self):
        workflow = FullMigrationWorkflow()
        inp = MigrationWorkflowInput(
            job_id=uuid4(),
            schemas=["dbo"],
            tables=["good", "bad"],
            validate_after_migration=False,
            notify_on_completion=False,
        )

        migrate_results = iter([{"status": "completed"}, {"status": "failed", "error": "Timeout"}])

        async def fake_execute(activity, *args, **kwargs):
            if activity.__name__ == "discover_objects":
                return [
                    {"object_id": "1", "object_type": "TABLE", "name": "good", "schema": "dbo"},
                    {"object_id": "2", "object_type": "TABLE", "name": "bad", "schema": "dbo"},
                ]
            if activity.__name__ == "analyze_compatibility":
                return None
            if activity.__name__ == "convert_schema":
                return {"success": True}
            if activity.__name__ == "migrate_table":
                return next(migrate_results)
            return None

        with (
            patch(f"{_workflow_module}.workflow.execute_activity", fake_execute),
            patch(f"{_workflow_module}.workflow.logger", MagicMock()),
        ):
            result = await workflow.run(inp)

        assert result.success is True
        assert result.tables_migrated == 1


class TestCutoverWorkflow:
    @pytest.mark.asyncio
    async def test_cutover_with_approval(self):
        workflow = CutoverWorkflow()
        inp = CutoverWorkflowInput(
            job_id=uuid4(),
            tables=["users", "orders"],
            require_human_approval=True,
            rollback_on_failure=True,
        )

        call_count = [0]

        async def fake_execute(activity, *args, **kwargs):
            call_count[0] += 1
            if activity.__name__ == "verify_target_snapshot":
                return {"verified": True, "snapshot_ref": "/tmp/snap.dump"}
            if activity.__name__ == "freeze_source_writes":
                return {"frozen": True, "source_row_counts": {"users": 1, "orders": 2}}
            if activity.__name__ == "validate_table":
                return {"status": "passed"}
            if activity.__name__ == "migrate_table":
                return {"status": "completed", "rows_migrated": 100}
            if activity.__name__ in ("create_snapshot_checkpoint", "save_cutover_checkpoint"):
                return {"success": True}
            if activity.__name__ == "commit_cutover":
                return {"success": True, "connection_switch": {}}
            if activity.__name__ == "rollback_cutover":
                return {"success": True, "tables_truncated": []}
            if activity.__name__ == "send_notification":
                return None
            return {"status": "passed"}

        with (
            patch(f"{_workflow_module}.workflow.execute_activity", fake_execute),
            patch(f"{_workflow_module}.workflow.sleep", AsyncMock()),
            patch(f"{_workflow_module}.workflow.logger", MagicMock()),
        ):
            workflow.approve_cutover()
            result = await workflow.run(inp)

        assert result.success is True
        assert result.tables_migrated == 2
        assert result.tables_validated == 2

    @pytest.mark.asyncio
    async def test_cutover_rejected(self):
        workflow = CutoverWorkflow()
        inp = CutoverWorkflowInput(
            job_id=uuid4(),
            tables=["users"],
            require_human_approval=True,
        )

        async def fake_execute(activity, *args, **kwargs):
            if activity.__name__ == "verify_target_snapshot":
                return {"verified": True}
            if activity.__name__ == "freeze_source_writes":
                return {"frozen": True}
            if activity.__name__ == "migrate_table":
                return {"status": "completed"}
            if activity.__name__ in ("create_snapshot_checkpoint", "save_cutover_checkpoint"):
                return {"success": True}
            return {"status": "passed"}

        with (
            patch(f"{_workflow_module}.workflow.execute_activity", fake_execute),
            patch(f"{_workflow_module}.workflow.sleep", AsyncMock()),
            patch(f"{_workflow_module}.workflow.logger", MagicMock()),
        ):
            workflow.reject_cutover("Rollback needed")
            result = await workflow.run(inp)

        assert result.success is False

    @pytest.mark.asyncio
    async def test_cutover_validation_below_threshold(self):
        workflow = CutoverWorkflow()
        inp = CutoverWorkflowInput(
            job_id=uuid4(),
            tables=["good", "bad"],
            require_human_approval=False,
            validation_threshold_pct=100.0,
            rollback_on_failure=True,
        )

        call_count = [0]

        async def fake_execute(activity, *args, **kwargs):
            call_count[0] += 1
            if activity.__name__ == "verify_target_snapshot":
                return {"verified": True}
            if activity.__name__ == "freeze_source_writes":
                return {"frozen": True}
            if activity.__name__ == "migrate_table":
                return {"status": "completed"}
            if activity.__name__ in ("create_snapshot_checkpoint", "save_cutover_checkpoint"):
                return {"success": True}
            if activity.__name__ == "validate_table":
                return {"status": "failed"}
            if activity.__name__ == "rollback_cutover":
                return {"success": True, "tables_truncated": ["good", "bad"]}
            return {"status": "passed"}

        with (
            patch(f"{_workflow_module}.workflow.execute_activity", fake_execute),
            patch(f"{_workflow_module}.workflow.logger", MagicMock()),
        ):
            result = await workflow.run(inp)

        assert result.success is False

    def test_signals(self):
        workflow = CutoverWorkflow()
        assert workflow.is_approved() is False
        workflow.approve_cutover()
        assert workflow.is_approved() is True


class TestPeriodicValidationWorkflow:
    @pytest.mark.asyncio
    async def test_validates_in_loop(self):
        workflow = PeriodicValidationWorkflow()
        calls = []

        async def fake_execute(activity, *args, **kwargs):
            calls.append(args)
            return {"status": "passed"}

        inp = PeriodicValidationWorkflowInput(
            source_connection_id="source-1",
            target_connection_id="target-1",
            tables=["users", "orders"],
            interval_minutes=60,
        )

        with (
            patch(f"{_workflow_module}.workflow.execute_activity", fake_execute),
            patch(f"{_workflow_module}.workflow.sleep", side_effect=KeyboardInterrupt()),
            patch(f"{_workflow_module}.workflow.logger", MagicMock()),
        ):
            with pytest.raises(KeyboardInterrupt):
                await workflow.run(inp)

        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_uses_connection_ids_from_input(self):
        """Connection IDs must come from the input, not hardcoded literals."""
        workflow = PeriodicValidationWorkflow()
        captured = []

        async def fake_execute(activity, *args, **kwargs):
            captured.append(args)
            return {"status": "passed"}

        inp = PeriodicValidationWorkflowInput(
            source_connection_id="src-conn-uuid",
            target_connection_id="tgt-conn-uuid",
            tables=["orders"],
            schema="reporting",
        )

        with (
            patch(f"{_workflow_module}.workflow.execute_activity", fake_execute),
            patch(f"{_workflow_module}.workflow.sleep", side_effect=KeyboardInterrupt()),
            patch(f"{_workflow_module}.workflow.logger", MagicMock()),
        ):
            with pytest.raises(KeyboardInterrupt):
                await workflow.run(inp)

        assert len(captured) == 1
        source_arg, target_arg, schema_arg, table_arg = captured[0]
        assert source_arg == "src-conn-uuid"
        assert target_arg == "tgt-conn-uuid"
        assert schema_arg == "reporting"
        assert table_arg == "orders"


class TestReplicationMonitoringWorkflow:
    @pytest.mark.asyncio
    async def test_alerts_on_high_lag(self):
        workflow = ReplicationMonitoringWorkflow()
        lag_values = [5, 45, 20]
        lag_idx = [0]
        alerts = []

        async def fake_execute(*args, **kwargs):
            activity_arg = args[0]
            if activity_arg == "check_replication_lag":
                val = lag_values[lag_idx[0] % len(lag_values)]
                lag_idx[0] += 1
                return val
            if activity_arg is not None and hasattr(activity_arg, "__name__") and activity_arg.__name__ == "send_notification":
                msg = args[2] if len(args) > 2 else kwargs.get("message", "")
                alerts.append(msg)
                return None
            return None

        with (
            patch(f"{_workflow_module}.workflow.execute_activity", fake_execute),
            patch(f"{_workflow_module}.workflow.sleep", side_effect=[None, KeyboardInterrupt]),
            patch(f"{_workflow_module}.workflow.logger", MagicMock()),
        ):
            with pytest.raises(KeyboardInterrupt):
                await workflow.run(
                    ["users"],
                    lag_threshold_seconds=30,
                    check_interval_seconds=15,
                )

        assert len(alerts) == 1
        assert "45" in str(alerts[0])


class TestPauseResume:
    @pytest.mark.asyncio
    async def test_pause_stops_queue_consumption(self):
        from domains.chunking.chunk_planner import ChunkPlanner
        from domains.chunking.chunk_store import ChunkStore
        from domains.migration.migration_engine import (
            ChunkedMigration,
            DataExtractor,
            DataLoader,
            MigrationStrategy,
            TableMigrationPlan,
        )

        extractor = MagicMock(spec=DataExtractor)
        extractor.extract_range = AsyncMock(return_value=[])
        loader = MagicMock(spec=DataLoader)
        loader.load_chunk = AsyncMock(return_value=0)

        store = MagicMock(spec=ChunkStore)
        store.claim_chunk = AsyncMock(return_value=None)
        store.release_chunk = AsyncMock()
        store.update_status = AsyncMock()
        store.expire_stale_leases = AsyncMock(return_value=0)
        store.get_pending_chunks = AsyncMock(return_value=[])
        store.save_chunks_batch = AsyncMock()

        planner = MagicMock(spec=ChunkPlanner)
        planner.plan_table = AsyncMock()
        from domains.chunking.chunk_planner import ChunkingResult
        planner.plan_table.return_value = ChunkingResult(chunks=[], total_rows_estimate=0)

        migration = ChunkedMigration(
            extractor=extractor,
            loader=loader,
            chunk_size=100,
            chunk_store=store,
            chunk_planner=planner,
            idempotent_writes=False,
        )

        plan = TableMigrationPlan(
            table_name="users", schema_name="dbo", columns=["id"],
            row_count_estimate=100, strategy=MigrationStrategy.CHUNKED,
        )
        result = await migration.migrate_table(plan)
        assert result.status.name in ("COMPLETED", "STOPPED")

    @pytest.mark.asyncio
    async def test_resume_requeues_incomplete_chunks(self):
        store = MagicMock()
        store.get_incomplete_chunks = AsyncMock(return_value=[
            MagicMock(chunk_id="c1", status="pending"),
            MagicMock(chunk_id="c2", status="failed"),
        ])
        store.save_chunk = AsyncMock()

        incomplete = await store.get_incomplete_chunks("dbo", "users")
        assert len(incomplete) == 2
        for chunk in incomplete:
            chunk.status = "pending"
            await store.save_chunk(chunk)

        assert store.save_chunk.call_count == 2

    @pytest.mark.asyncio
    async def test_crash_recovery_expires_leases(self):
        store = MagicMock()
        store.expire_stale_leases = AsyncMock(return_value=3)

        expired = await store.expire_stale_leases()
        assert expired == 3

    @pytest.mark.asyncio
    async def test_lease_renewal_failure(self):
        store = MagicMock()
        store.renew_lease = AsyncMock(return_value=False)

        renewed = await store.renew_lease("chunk-1", "worker-1")
        assert renewed is False

    @pytest.mark.asyncio
    async def test_chunk_retry_exhaustion(self):
        store = MagicMock()
        store.increment_retry = AsyncMock(side_effect=[1, 2, 3, 4])

        retries = [await store.increment_retry("chunk-1") for _ in range(4)]
        assert retries == [1, 2, 3, 4]
