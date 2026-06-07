"""
Module: apps/replicator/capture/agent.py
Purpose: CaptureAgent orchestrates the capture loop — poll, normalize, publish
Author: Migration Platform Team
Created: 2026-05-22
Domain: Replication / Capture
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from apps.replicator.capture.models import CaptureBatch, TableInfo
from apps.replicator.capture.providers.base import AbstractCaptureProvider
from apps.replicator.capture.publisher import MessagePublisher

logger = logging.getLogger(__name__)


class CaptureAgent:
    """Orchestrates the continuous capture loop for a set of tables.

    Polls the configured provider for changes, normalizes events,
    and publishes them to the message broker.
    """

    def __init__(
        self,
        provider: AbstractCaptureProvider,
        publisher: MessagePublisher,
        poll_interval_ms: int = 1000,
        batch_size: int = 1000,
    ) -> None:
        self._provider = provider
        self._publisher = publisher
        self._poll_interval = poll_interval_ms / 1000.0
        self._batch_size = batch_size
        self._running = False
        self._paused = False
        # Event is SET while running and CLEARED while paused. A paused capture
        # loop awaits this event rather than busy-sleeping.
        self._paused_event = asyncio.Event()
        self._paused_event.set()
        self._last_positions: dict[str, bytes | None] = {}
        self.progress: dict[str, dict[str, Any]] = {}
        self.events_captured = 0
        # Fix 2.5: track tasks so stop() can cancel them individually and await completion.
        self._tasks: list[asyncio.Task] = []

    async def start(
        self,
        schema: str,
        table_names: list[str] | None = None,
    ) -> list[TableInfo]:
        """Begin capturing changes for tables in the given schema.

        Discovers tables, optionally filters to ``table_names``, then launches
        a polling loop for each.

        Args:
            schema: Database schema to replicate.
            table_names: Optional allow-list of table names (case-insensitive).

        Returns:
            List of discovered TableInfo.
        """
        tables = await self.discover_tables(schema)
        if table_names:
            allowed = {n.lower() for n in table_names}
            tables = [t for t in tables if t.table_name.lower() in allowed]
        if not tables:
            logger.warning("No tables discovered in schema '%s'", schema)
            return tables

        self._running = True
        for table in tables:
            # Fix 2.5: store tasks so stop() can cancel + await them.
            task = asyncio.create_task(
                self._capture_loop(table),
                name=f"capture:{table.qualified_name}",
            )
            self._tasks.append(task)

        logger.info("CaptureAgent started for %d tables in schema '%s'", len(tables), schema)
        return tables

    async def pause(self) -> None:
        """Pause the capture loop.

        Clears the pause event so each capture loop blocks on it at the next
        iteration boundary — no polling occurs while paused.
        """
        self._paused = True
        self._paused_event.clear()
        logger.info("CaptureAgent paused")

    async def resume(self) -> None:
        """Resume the capture loop by releasing all loops waiting on the event."""
        self._paused = False
        self._paused_event.set()
        logger.info("CaptureAgent resumed")

    def get_progress(self) -> dict[str, Any]:
        """Return current progress and status."""
        return {
            "running": self._running,
            "paused": self._paused,
            "events_captured": self.events_captured,
            "tables": dict(self.progress),
            "tables_count": len(self.progress),
        }

    async def stop(self) -> None:
        """Gracefully stop all capture loops.

        Fix 2.5: cancels every tracked task and awaits completion so the caller
        knows all loops have exited before stop() returns.
        """
        self._running = False
        self._paused = False
        self._paused_event.set()
        # Cancel all tracked tasks and wait for them to finish.
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("CaptureAgent stopped")

    async def discover_tables(self, schema: str) -> list[TableInfo]:
        """Discover tables available for replication.

        Args:
            schema: Database schema.

        Returns:
            List of table metadata.
        """
        return await self._provider.discover_tables(schema)

    async def _capture_loop(self, table: TableInfo) -> None:
        """Continuous capture loop for a single table."""
        while self._running:
            if not self._paused_event.is_set():
                # Block until resumed or stopped — no busy polling.
                await self._paused_event.wait()
                continue
            try:
                count = await self._capture_and_publish(table)
                if count == 0:
                    await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in capture loop for %s", table.qualified_name)
                await asyncio.sleep(self._poll_interval * 5)

    async def _capture_and_publish(self, table: TableInfo) -> int:
        """Capture a batch of changes and publish them.

        Args:
            table: Table to capture from.

        Returns:
            Number of events captured and published.
        """
        last_pos = self._last_positions.get(table.qualified_name)
        batch: CaptureBatch = await self._provider.capture_changes(
            table=table,
            last_position=last_pos,
            batch_size=self._batch_size,
        )

        if not batch.changes:
            return 0

        for event in batch.changes:
            event.source_timestamp = datetime.now(UTC)
            await self._publisher.publish(event)

        self._last_positions[table.qualified_name] = (
            batch.new_position.serialize() if batch.new_position else None
        )

        self.events_captured += len(batch.changes)
        self.progress[table.qualified_name] = {
            "events_captured": self.events_captured,
            "last_position": (
                batch.new_position.serialize().hex() if batch.new_position else None
            ),
            "last_captured_at": datetime.now(UTC).isoformat(),
        }

        return len(batch.changes)
