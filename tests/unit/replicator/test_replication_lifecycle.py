"""
Module: test_replication_lifecycle.py
Purpose: Unit tests
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import AsyncMock

import pytest

from apps.replicator.capture.agent import CaptureAgent
from apps.replicator.capture.models import (
    CaptureBatch,
    ChangeEvent,
    ChangeOperation,
    LsnPosition,
    TableInfo,
)
from apps.replicator.orchestrator.commands import (
    get_status,
    pause_replication,
    register_capture_agent,
    resume_replication,
    set_scheduler,
    start_replication,
    stop_replication,
)
from apps.replicator.orchestrator.models import ReplicationConfig
from apps.replicator.orchestrator.scheduler import Scheduler
from apps.replicator.orchestrator.state_machine import (
    ReplicationEvent,
    ReplicationState,
    StateMachine,
)


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    lsn = LsnPosition.from_string("0x00000000:00000000:0000")
    provider.discover_tables.return_value = [
        TableInfo(schema_name="dbo", table_name="users", columns=["id", "name"], pk_columns=["id"]),
    ]
    provider.capture_changes.return_value = CaptureBatch(changes=[], new_position=lsn)
    return provider


@pytest.fixture
def mock_publisher():
    publisher = AsyncMock()
    publisher.publish.return_value = True
    return publisher


@pytest.fixture
def agent(mock_provider, mock_publisher):
    return CaptureAgent(provider=mock_provider, publisher=mock_publisher)


def make_event() -> ChangeEvent:
    lsn = LsnPosition.from_string("0x00001234:0000ABCD:0001")
    return ChangeEvent(
        table_schema="dbo",
        table_name="users",
        operation=ChangeOperation.INSERT,
        after_values={"id": 1},
        lsn=lsn,
    )


class TestCaptureAgentLifecycle:
    @pytest.mark.asyncio
    async def test_capture_agent_pause_resume(self, agent):
        assert agent._paused is False

        await agent.pause()
        assert agent._paused is True

        await agent.resume()
        assert agent._paused is False

    @pytest.mark.asyncio
    async def test_capture_agent_stop(self, agent):
        agent._running = True
        assert agent._running is True

        await agent.stop()
        assert agent._running is False
        assert agent._paused is False

    @pytest.mark.asyncio
    async def test_capture_agent_progress(self, agent, mock_provider, mock_publisher):
        lsn = LsnPosition.from_string("0x00001234:0000ABCD:0005")
        event = ChangeEvent(
            table_schema="dbo",
            table_name="users",
            operation=ChangeOperation.UPDATE,
            after_values={"id": 42, "name": "Bob"},
            lsn=lsn,
        )
        mock_provider.capture_changes.return_value = CaptureBatch(changes=[event], new_position=lsn)

        table = TableInfo(
            schema_name="dbo",
            table_name="users",
            columns=["id", "name"],
            pk_columns=["id"],
        )
        await agent._capture_and_publish(table)

        assert agent.events_captured == 1
        assert "dbo.users" in agent.progress
        assert agent.progress["dbo.users"]["events_captured"] == 1
        assert agent.progress["dbo.users"]["last_position"] == lsn.serialize().hex()

    @pytest.mark.asyncio
    async def test_capture_agent_multiple_pause_resume(self, agent):
        for _ in range(3):
            await agent.pause()
            assert agent._paused is True
            await agent.resume()
            assert agent._paused is False

    @pytest.mark.asyncio
    async def test_capture_agent_pause_loop_skips_capture(self, agent, mock_provider):
        # Drive pause/resume via the public API: the loop is event-driven, so
        # pausing clears the pause event and the loop blocks without polling
        # (Issue #19). Setting the bare _paused flag is no longer sufficient.
        agent._running = True
        await agent.pause()

        table = TableInfo(
            schema_name="dbo",
            table_name="users",
            columns=["id", "name"],
            pk_columns=["id"],
        )

        task = asyncio.create_task(agent._capture_loop(table))
        await asyncio.sleep(0.3)

        assert mock_provider.capture_changes.await_count == 0

        await agent.resume()
        await asyncio.sleep(0.3)

        assert mock_provider.capture_changes.await_count > 0

        agent._running = False
        await agent.stop()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_get_progress_returns_state(self, agent):
        agent._running = True
        agent._paused = False
        progress = agent.get_progress()
        assert progress["running"] is True
        assert progress["paused"] is False
        assert progress["events_captured"] == 0
        assert progress["tables"] == {}
        assert progress["tables_count"] == 0

    @pytest.mark.asyncio
    async def test_get_progress_reflects_paused_state(self, agent):
        await agent.pause()
        progress = agent.get_progress()
        assert progress["paused"] is True


class TestSchedulerLifecycle:
    @pytest.mark.asyncio
    async def test_scheduler_pause_resume_replication(self):
        scheduler = Scheduler()
        capture_agent = AsyncMock(spec=CaptureAgent)

        sm = StateMachine()
        sm.transition(ReplicationEvent.START)
        sm.transition(ReplicationEvent.CATCHUP_DONE)
        assert sm.current_state == ReplicationState.CDC_STREAMING

        config = ReplicationConfig(
            id="sched-lifecycle",
            name="Lifecycle Test",
            source_conn={"host": "src"},
            target_conn={"host": "tgt"},
            tables=["users"],
        )
        scheduler.register_replication("sched-lifecycle", capture_agent, sm, config)

        pause_result = await scheduler.pause_replication("sched-lifecycle")
        assert pause_result["state"] == ReplicationState.PAUSED.value
        assert sm.current_state == ReplicationState.PAUSED
        capture_agent.pause.assert_awaited_once()

        resume_result = await scheduler.resume_replication("sched-lifecycle")
        assert resume_result["state"] == ReplicationState.CDC_STREAMING.value
        assert sm.current_state == ReplicationState.CDC_STREAMING
        capture_agent.resume.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_scheduler_stop_replication(self):
        scheduler = Scheduler()
        capture_agent = AsyncMock(spec=CaptureAgent)

        sm = StateMachine()
        sm.transition(ReplicationEvent.START)
        sm.transition(ReplicationEvent.CATCHUP_DONE)

        config = ReplicationConfig(
            id="sched-stop",
            name="Stop Test",
            source_conn={"host": "src"},
            target_conn={"host": "tgt"},
            tables=["orders"],
        )
        scheduler.register_replication("sched-stop", capture_agent, sm, config)

        result = await scheduler.stop_replication("sched-stop")
        assert result["state"] == "COMPLETED"
        capture_agent.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_scheduler_get_replication_status(self):
        scheduler = Scheduler()
        capture_agent = AsyncMock(spec=CaptureAgent)
        capture_agent.get_progress.return_value = {
            "running": True,
            "paused": False,
            "events_captured": 42,
            "tables": {"dbo.users": {"events_captured": 42}},
            "tables_count": 1,
        }

        sm = StateMachine()
        sm.transition(ReplicationEvent.START)
        sm.transition(ReplicationEvent.CATCHUP_DONE)

        config = ReplicationConfig(
            id="sched-status",
            name="Status Test",
            source_conn={"host": "src"},
            target_conn={"host": "tgt"},
            tables=["users"],
        )
        scheduler.register_replication("sched-status", capture_agent, sm, config)

        status = scheduler.get_replication_status("sched-status")
        assert status["active"] is True
        assert status["state"] == ReplicationState.CDC_STREAMING.value
        assert status["events_captured"] == 42
        assert status["tables_count"] == 1

    @pytest.mark.asyncio
    async def test_scheduler_get_replication_status_not_active(self):
        scheduler = Scheduler()
        status = scheduler.get_replication_status("unknown")
        assert status["active"] is False

    @pytest.mark.asyncio
    async def test_scheduler_register_replication(self):
        scheduler = Scheduler()
        capture_agent = AsyncMock(spec=CaptureAgent)
        sm = StateMachine()
        config = ReplicationConfig(
            id="sched-reg",
            name="Reg Test",
            source_conn={"host": "src"},
            target_conn={"host": "tgt"},
            tables=["items"],
        )
        scheduler.register_replication("sched-reg", capture_agent, sm, config)
        status = scheduler.get_replication_status("sched-reg")
        assert status["active"] is True

    @pytest.mark.asyncio
    async def test_scheduler_pause_nonexistent_raises(self):
        scheduler = Scheduler()
        with pytest.raises(ValueError, match="No replication registered"):
            await scheduler.pause_replication("nonexistent")


class TestCommandsLifecycle:
    @pytest.mark.asyncio
    async def test_commands_pause_resume_with_scheduler(self):
        scheduler = Scheduler()
        set_scheduler(scheduler)

        capture_agent = AsyncMock(spec=CaptureAgent)
        capture_agent.get_progress.return_value = {
            "running": True,
            "paused": False,
            "events_captured": 0,
            "tables": {},
            "tables_count": 0,
        }

        sm = StateMachine()
        sm.transition(ReplicationEvent.START)
        sm.transition(ReplicationEvent.CATCHUP_DONE)

        config = ReplicationConfig(
            id="cmd-lifecycle",
            name="Cmd Lifecycle",
            source_conn={"host": "src"},
            target_conn={"host": "tgt"},
            tables=["users"],
        )
        scheduler.register_replication("cmd-lifecycle", capture_agent, sm, config)

        result = await pause_replication("cmd-lifecycle")
        assert result.success is True
        assert result.data["state"] == ReplicationState.PAUSED.value
        assert sm.current_state == ReplicationState.PAUSED
        capture_agent.pause.assert_awaited_once()

        result = await resume_replication("cmd-lifecycle")
        assert result.success is True
        assert result.data["state"] == ReplicationState.CDC_STREAMING.value
        assert sm.current_state == ReplicationState.CDC_STREAMING
        capture_agent.resume.assert_awaited_once()

        result = await stop_replication("cmd-lifecycle")
        assert result.success is True
        capture_agent.stop.assert_awaited_once()

        set_scheduler(None)

    @pytest.mark.asyncio
    async def test_commands_pause_resume_with_capture_agent(self):
        config = ReplicationConfig(
            id="cmd-agent-lifecycle",
            name="Cmd Agent Lifecycle",
            source_conn={"host": "src"},
            target_conn={"host": "tgt"},
            tables=["products"],
        )
        await start_replication("cmd-agent-lifecycle", ["products"], config)

        from apps.replicator.orchestrator.commands import _active_replications

        sm, _ = _active_replications["cmd-agent-lifecycle"]
        sm.transition(ReplicationEvent.SNAPSHOT_BEGIN)

        agent = CaptureAgent(
            provider=AsyncMock(),
            publisher=AsyncMock(),
        )
        register_capture_agent("cmd-agent-lifecycle", agent)

        result = await pause_replication("cmd-agent-lifecycle")
        assert result.success is True
        assert agent._paused is True

        result = await resume_replication("cmd-agent-lifecycle")
        assert result.success is True
        assert agent._paused is False

    @pytest.mark.asyncio
    async def test_commands_get_status_with_progress(self):
        config = ReplicationConfig(
            id="cmd-status-progress",
            name="Status Progress",
            source_conn={"host": "src"},
            target_conn={"host": "tgt"},
            tables=["logs"],
        )
        await start_replication("cmd-status-progress", ["logs"], config)

        agent = CaptureAgent(
            provider=AsyncMock(),
            publisher=AsyncMock(),
        )
        agent.events_captured = 99
        register_capture_agent("cmd-status-progress", agent)

        result = await get_status("cmd-status-progress")
        assert result.success is True
        assert result.data is not None
        assert result.data["events_captured"] == 99
