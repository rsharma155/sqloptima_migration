"""
Module: apps/replicator/capture/providers/base.py
Purpose: Abstract base class for all capture providers (CDC, Change Tracking, Watermark)
Author: Migration Platform Team
Created: 2026-05-22
Domain: Replication / Capture
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from apps.replicator.capture.models import CaptureBatch, ChangeEvent, TableInfo


class AbstractCaptureProvider(ABC):
    """Pluggable capture provider interface for SQL Server change data sources.

    Implementations handle:
    - SQL Server Enterprise CDC (fn_cdc_get_all_changes_*)
    - Change Tracking (CHANGE_TRACKING_CURRENT_VERSION)
    - Timestamp/watermark column polling
    """

    @abstractmethod
    async def connect(self, connection_string: str) -> None:
        """Establish connection to the source database.

        Args:
            connection_string: Source database connection string.

        Raises:
            ConnectionError: If connection fails.
        """

    @abstractmethod
    async def discover_tables(self, schema: str) -> list[TableInfo]:
        """Discover tables available for replication in the given schema.

        Args:
            schema: Database schema to scan.

        Returns:
            List of TableInfo with column and PK metadata.
        """

    @abstractmethod
    async def capture_changes(
        self,
        table: TableInfo,
        last_position: bytes | None,
        batch_size: int = 1000,
    ) -> CaptureBatch:
        """Capture a batch of changes since the last known position.

        Args:
            table: Target table metadata.
            last_position: Last known LSN/position (None for initial).
            batch_size: Maximum number of change events to return.

        Returns:
            CaptureBatch containing change events and new position.
        """

    @abstractmethod
    async def take_snapshot(
        self,
        table: TableInfo,
        callback: Callable[[list[ChangeEvent]], Awaitable[None]],
        chunk_size: int = 10000,
    ) -> None:
        """Take a full snapshot of the table, streaming chunks via callback.

        Args:
            table: Target table metadata.
            callback: Async callback invoked with each chunk of ChangeEvents.
            chunk_size: Number of rows per chunk.
        """
