"""
Module: tests/unit/replicator/test_cdc_resume_and_snapshot.py
Purpose: Phase 1 — ABC, seed_positions, checkpoint load_all, snapshot FSM
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from application.replication_runtime import (
    ReplicationRuntimeManager,
    _source_positions_from_checkpoints,
)
from apps.replicator.apply.checkpoint import CheckpointEntry, CheckpointStore
from apps.replicator.capture.agent import CaptureAgent
from apps.replicator.capture.models import TableInfo
from apps.replicator.capture.providers.base import AbstractCaptureProvider
from apps.replicator.capture.providers.cdc_provider import SqlServerCdcProvider
from apps.replicator.orchestrator.state_machine import ReplicationState
from domains.replication.entities import ReplicationStreamConfig, StreamTableConfig


class TestSqlServerCdcProviderAbc:
    def test_is_abstract_capture_provider(self) -> None:
        provider = SqlServerCdcProvider(connector=MagicMock())
        assert isinstance(provider, AbstractCaptureProvider)


class TestCaptureAgentSeedPositions:
    def test_seed_positions_sets_last_positions(self) -> None:
        provider = AsyncMock()
        publisher = AsyncMock()
        agent = CaptureAgent(provider=provider, publisher=publisher)
        lsn = b"\x00" * 10
        agent.seed_positions({"dbo.orders": lsn, "dbo.users": None})
        assert agent.last_positions["dbo.orders"] == lsn
        assert agent.last_positions["dbo.users"] is None


class TestCheckpointStoreLoadAll:
    @pytest.mark.asyncio
    async def test_load_all_without_schema(self) -> None:
        conn = AsyncMock()
        lsn = b"\x01" * 10
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "table_schema": "public",
                    "table_name": "orders",
                    "lsn_bytes": lsn,
                    "rows_applied": 5,
                    "updated_at": datetime(2026, 6, 1, tzinfo=UTC),
                }
            ]
        )
        store = CheckpointStore(conn)
        rows = await store.load_all()
        assert len(rows) == 1
        assert rows[0].table_name == "orders"
        assert rows[0].lsn_bytes == lsn
        conn.fetch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_load_all_filtered_by_schema(self) -> None:
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        store = CheckpointStore(conn)
        await store.load_all("public")
        sql = conn.fetch.call_args[0][0]
        assert "WHERE table_schema = $1" in sql
        assert conn.fetch.call_args[0][1] == "public"


class TestSourcePositionMapping:
    def test_maps_target_checkpoint_to_source_key(self) -> None:
        config = ReplicationStreamConfig(
            stream_id="s1",
            name="test",
            source_connection_id="src",
            target_connection_id="tgt",
            source_schema="dbo",
            target_schema="public",
            tables=[
                StreamTableConfig(name="Orders", pk_columns=["id"]),
            ],
        )
        cp = CheckpointEntry(
            table_schema="public",
            table_name="orders",
            lsn_bytes=b"\x02" * 10,
        )
        positions = _source_positions_from_checkpoints(config, [cp])
        assert positions == {"dbo.Orders": b"\x02" * 10}


class TestReplicationRuntimeSnapshotFsm:
    @pytest.mark.asyncio
    async def test_snapshot_path_when_no_checkpoints(self) -> None:
        mgr = ReplicationRuntimeManager()
        stream_id = "snap-1"
        config = ReplicationStreamConfig(
            stream_id=stream_id,
            name="snap-test",
            source_connection_id="src",
            target_connection_id="tgt",
            source_schema="dbo",
            target_schema="public",
            tables=[StreamTableConfig(name="users", pk_columns=["id"])],
            poll_interval_ms=100,
            batch_size=10,
        )

        provider = AsyncMock(spec=AbstractCaptureProvider)
        provider.discover_tables = AsyncMock(
            return_value=[
                TableInfo(
                    schema_name="dbo",
                    table_name="users",
                    columns=["id", "name"],
                    pk_columns=["id"],
                )
            ]
        )
        provider.take_snapshot = AsyncMock()
        provider.capture_changes = AsyncMock(
            side_effect=Exception("should not poll in this test")
        )

        target_conn = AsyncMock()
        target_conn.execute = AsyncMock()
        target_conn.fetch = AsyncMock(return_value=[])  # no checkpoints
        target_conn.fetchrow = AsyncMock(return_value=None)

        # Stop agent immediately after start by making discover return tables
        # then cancelling via stop — capture loop will error once; we stop right after.
        runtime = await mgr.start_stream(
            config,
            provider=provider,
            target_connection=target_conn,
            table_infos=[
                TableInfo(
                    schema_name="dbo",
                    table_name="users",
                    columns=["id", "name"],
                    pk_columns=["id"],
                )
            ],
        )
        try:
            provider.take_snapshot.assert_awaited()
            assert runtime.state_machine.current_state == ReplicationState.CDC_STREAMING
            history = [t.event.value for t in runtime.state_machine.transitions_history]
            assert "SNAPSHOT_BEGIN" in history
            assert "SNAPSHOT_DONE" in history
            assert "CATCHUP_DONE" in history
        finally:
            await mgr.stop_stream(stream_id)

    @pytest.mark.asyncio
    async def test_skips_snapshot_when_checkpoint_exists(self) -> None:
        mgr = ReplicationRuntimeManager()
        stream_id = "resume-1"
        config = ReplicationStreamConfig(
            stream_id=stream_id,
            name="resume-test",
            source_connection_id="src",
            target_connection_id="tgt",
            source_schema="dbo",
            target_schema="public",
            tables=[StreamTableConfig(name="users", pk_columns=["id"])],
            poll_interval_ms=100,
            batch_size=10,
        )

        provider = AsyncMock(spec=AbstractCaptureProvider)
        provider.discover_tables = AsyncMock(
            return_value=[
                TableInfo(
                    schema_name="dbo",
                    table_name="users",
                    columns=["id"],
                    pk_columns=["id"],
                )
            ]
        )
        provider.take_snapshot = AsyncMock()
        provider.capture_changes = AsyncMock(
            side_effect=Exception("stop poll")
        )

        lsn = b"\x03" * 10
        target_conn = AsyncMock()
        target_conn.execute = AsyncMock()
        target_conn.fetch = AsyncMock(
            return_value=[
                {
                    "table_schema": "public",
                    "table_name": "users",
                    "lsn_bytes": lsn,
                    "rows_applied": 1,
                    "updated_at": datetime(2026, 6, 1, tzinfo=UTC),
                }
            ]
        )

        runtime = await mgr.start_stream(
            config,
            provider=provider,
            target_connection=target_conn,
            table_infos=[
                TableInfo(
                    schema_name="dbo",
                    table_name="users",
                    columns=["id"],
                    pk_columns=["id"],
                )
            ],
        )
        try:
            provider.take_snapshot.assert_not_awaited()
            assert runtime.capture_agent is not None
            assert runtime.capture_agent.last_positions.get("dbo.users") == lsn
            history = [t.event.value for t in runtime.state_machine.transitions_history]
            assert "SNAPSHOT_BEGIN" not in history
            assert "CATCHUP_DONE" in history
            assert runtime.state_machine.current_state == ReplicationState.CDC_STREAMING
        finally:
            await mgr.stop_stream(stream_id)
