"""
Module: tests/unit/replicator/test_capture_agent.py
Purpose: Unit tests for CaptureAgent orchestrator
Author: Migration Platform Team
Created: 2026-05-22
Domain: Replication / Capture
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

import asyncio
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


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.discover_tables.return_value = [
        TableInfo(schema_name="dbo", table_name="users", columns=["id", "name"], pk_columns=["id"]),
    ]
    lsn = LsnPosition.from_string("0x00000000:00000000:0000")
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


class TestCaptureAgent:
    @pytest.mark.asyncio
    async def test_start_runs_capture_loop(self, agent, mock_provider, mock_publisher):
        lsn = LsnPosition.from_string("0x00001234:0000ABCD:0001")
        event = ChangeEvent(
            table_schema="dbo", table_name="users",
            operation=ChangeOperation.INSERT, after_values={"id": 1},
            lsn=lsn,
        )
        call_count = [0]

        async def capture_side_effect(table, last_position=None, batch_size=1000):
            call_count[0] += 1
            if call_count[0] >= 3:
                agent._running = False
            return CaptureBatch(
                changes=[event],
                new_position=lsn,
            )

        mock_provider.capture_changes.side_effect = capture_side_effect
        tables = await agent.start(schema="dbo")
        assert len(tables) == 1
        assert tables[0].table_name == "users"

    @pytest.mark.asyncio
    async def test_stop_halts_capture_loop(self, agent):
        agent._running = True
        await agent.stop()
        assert agent._running is False

    @pytest.mark.asyncio
    async def test_discover_tables_delegates(self, agent, mock_provider):
        tables = await agent.discover_tables("sales")
        mock_provider.discover_tables.assert_awaited_once_with("sales")
        assert len(tables) == 1

    @pytest.mark.asyncio
    async def test_capture_and_publish_flow(self, agent, mock_provider, mock_publisher):
        lsn = LsnPosition.from_string("0x00001234:0000ABCD:0005")
        event = ChangeEvent(
            table_schema="dbo", table_name="users",
            operation=ChangeOperation.UPDATE, after_values={"id": 42, "name": "Bob"},
            lsn=lsn,
        )
        mock_provider.capture_changes.return_value = CaptureBatch(changes=[event], new_position=lsn)

        table = TableInfo(
            schema_name="dbo", table_name="users",
            columns=["id", "name"], pk_columns=["id"],
        )
        result = await agent._capture_and_publish(table)
        assert result == 1
        mock_publisher.publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_capture_and_publish_empty_batch(self, agent, mock_publisher):
        lsn = LsnPosition.from_string("0x00000000:00000000:0000")
        agent._provider.capture_changes.return_value = CaptureBatch(changes=[], new_position=lsn)

        table = TableInfo(schema_name="dbo", table_name="users", columns=["id"], pk_columns=["id"])
        result = await agent._capture_and_publish(table)
        assert result == 0
        mock_publisher.publish.assert_not_called()


class TestCaptureAgentPause:
    """Event-based pause semantics (Issue #19) — paused loops await an
    asyncio.Event instead of busy-sleeping, and stop() unblocks them."""

    @pytest.mark.asyncio
    async def test_initial_state_is_not_paused(self, agent):
        assert agent._paused is False
        assert agent._paused_event.is_set() is True

    @pytest.mark.asyncio
    async def test_pause_clears_event(self, agent):
        await agent.pause()
        assert agent._paused is True
        assert agent._paused_event.is_set() is False

    @pytest.mark.asyncio
    async def test_resume_sets_event(self, agent):
        await agent.pause()
        await agent.resume()
        assert agent._paused is False
        assert agent._paused_event.is_set() is True

    @pytest.mark.asyncio
    async def test_stop_unblocks_event(self, agent):
        await agent.pause()
        await agent.stop()
        # stop() must release any loop awaiting the pause event so it can exit.
        assert agent._paused_event.is_set() is True

    @pytest.mark.asyncio
    async def test_paused_loop_does_not_poll_and_stop_exits(self, agent, mock_provider):
        """While paused the loop must not poll the provider (no busy-loop), and
        stop() must let the awaiting loop terminate promptly."""
        await agent.pause()
        agent._running = True
        table = TableInfo(
            schema_name="dbo", table_name="users",
            columns=["id"], pk_columns=["id"],
        )
        loop_task = asyncio.create_task(agent._capture_loop(table))
        await asyncio.sleep(0.05)

        mock_provider.capture_changes.assert_not_called()

        await agent.stop()
        await asyncio.wait_for(loop_task, timeout=1.0)
        assert loop_task.done()

    @pytest.mark.asyncio
    async def test_resume_lets_loop_poll_again(self, agent, mock_provider):
        lsn = LsnPosition.from_string("0x00000000:00000000:0000")
        mock_provider.capture_changes.return_value = CaptureBatch(changes=[], new_position=lsn)
        await agent.pause()
        agent._running = True
        table = TableInfo(
            schema_name="dbo", table_name="users",
            columns=["id"], pk_columns=["id"],
        )
        loop_task = asyncio.create_task(agent._capture_loop(table))
        await asyncio.sleep(0.05)
        mock_provider.capture_changes.assert_not_called()

        await agent.resume()
        await asyncio.sleep(0.05)
        assert mock_provider.capture_changes.await_count >= 1

        await agent.stop()
        await asyncio.wait_for(loop_task, timeout=1.0)
