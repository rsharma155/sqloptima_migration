"""
Module: tests/unit/replicator/test_capture_agent_lifecycle.py
Purpose: TDD tests for DBA feedback fix 2.5 — CaptureAgent tasks must be
         tracked and cancellable; stop() must await task completion.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.replicator.capture.agent import CaptureAgent
from apps.replicator.capture.models import CaptureBatch, LsnPosition, TableInfo
from apps.replicator.capture.providers.base import AbstractCaptureProvider
from apps.replicator.capture.publisher import MessagePublisher


def _make_table(name: str = "users") -> TableInfo:
    return TableInfo(
        schema_name="dbo",
        table_name=name,
        columns=["id", "name"],
        watermark_column="modified_at",
    )


class _NullProvider(AbstractCaptureProvider):
    async def connect(self, connection_string: str) -> None:
        pass

    async def discover_tables(self, schema: str):
        return [_make_table("t1"), _make_table("t2")]

    async def capture_changes(self, table, last_position, batch_size=1000):
        await asyncio.sleep(0)
        return CaptureBatch(changes=[], new_position=LsnPosition(raw_bytes=b""))

    async def take_snapshot(self, table, callback, chunk_size=10000):
        pass


class _NullPublisher(MessagePublisher):
    async def publish(self, event):
        pass


@pytest.fixture
def agent():
    return CaptureAgent(
        provider=_NullProvider(),
        publisher=_NullPublisher(),
        poll_interval_ms=10,
        batch_size=100,
    )


class TestCaptureAgentTaskLifecycle:
    """
    Issue 2.5: CaptureAgent tasks must be stored and cancellable.
    """

    @pytest.mark.asyncio
    async def test_start_creates_tracked_tasks(self, agent):
        """start() must store one asyncio.Task per table."""
        tables = await agent.start(schema="dbo")
        assert len(tables) == 2
        # Tasks must be tracked
        assert hasattr(agent, "_tasks"), "CaptureAgent must have a _tasks list"
        assert len(agent._tasks) == 2, (
            f"Expected 2 tracked tasks, got {len(agent._tasks)}"
        )
        await agent.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_all_tasks(self, agent):
        """stop() must cancel every tracked task and clear the list."""
        await agent.start(schema="dbo")
        assert len(agent._tasks) == 2
        await agent.stop()
        # After stop, tasks should be cancelled / done
        for task in agent._tasks:
            assert task.done() or task.cancelled(), (
                "Task was not cancelled after stop()"
            )

    @pytest.mark.asyncio
    async def test_stop_clears_task_list(self, agent):
        """stop() must clear _tasks so the agent can be restarted cleanly."""
        await agent.start(schema="dbo")
        await agent.stop()
        assert len(agent._tasks) == 0, (
            f"Task list was not cleared after stop(): {len(agent._tasks)} tasks remain"
        )

    @pytest.mark.asyncio
    async def test_running_false_after_stop(self, agent):
        await agent.start(schema="dbo")
        await agent.stop()
        assert not agent._running
