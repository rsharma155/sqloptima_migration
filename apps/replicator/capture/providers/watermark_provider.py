# ruff: noqa: ARG002
"""
Module: apps/replicator/capture/providers/watermark_provider.py
Purpose: Timestamp/sequence column polling provider for incremental capture.
         Fix 2.1 — soft-delete support: rows with a truthy soft_delete_column
                    emit ChangeOperation.DELETE events.
         Fix 2.2 — resume position tracks actual max watermark value, not a
                    hardcoded zero LSN placeholder.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from apps.replicator.capture.models import (
    CaptureBatch,
    ChangeEvent,
    ChangeOperation,
    TableInfo,
    WatermarkPosition,
)
from apps.replicator.capture.providers.base import AbstractCaptureProvider


class WatermarkProvider(AbstractCaptureProvider):
    """Captures changes by polling a watermark column (timestamp, sequence, etc.).

    Works with any SQL Server edition. Uses a monotonically increasing column
    (e.g., LastModifiedDate, RowVersion) to detect new and modified rows.

    Limitations:
      - Hard DELETEs are invisible (watermark polling can only see existing rows).
        Workaround: use a soft-delete column (see Fix 2.1 — soft_delete_column on
        TableInfo). When soft_delete_column is set, rows with a truthy value for
        that column are emitted as DELETE events with before_values populated.
      - Duplicate events are possible if the watermark is not strictly monotonic
        (e.g., two rows updated at the same timestamp within the same poll window).
        The downstream Deduplicator handles this via LSN-based dedup.
    """

    def __init__(self) -> None:
        self._connection_string: str = ""

    async def connect(self, connection_string: str) -> None:
        if not connection_string:
            raise ValueError("connection_string must not be empty")
        self._connection_string = connection_string

    async def discover_tables(self, schema: str) -> list[TableInfo]:
        return await self._fetch_table_list(schema)

    async def _fetch_table_list(self, schema: str) -> list[TableInfo]:
        """Override in subclass with actual DB introspection logic."""
        return []

    async def capture_changes(
        self,
        table: TableInfo,
        last_position: bytes | None,
        batch_size: int = 1000,
    ) -> CaptureBatch:
        """Poll for rows where watermark > last_position.

        Fix 2.1: rows where soft_delete_column is truthy emit DELETE events
                 with before_values set to the row (pk-based delete on target).
        Fix 2.2: new_position reflects the actual max watermark from this batch,
                 not a hardcoded zero-LSN placeholder.

        Args:
            table: Table metadata including watermark_column and optional
                   soft_delete_column.
            last_position: Previous watermark value as UTF-8 bytes, or None for
                           initial capture.
            batch_size: Maximum rows to fetch.

        Returns:
            CaptureBatch with events and the updated watermark position.
        """
        watermark_col = table.watermark_column or "modified"
        last_value = last_position.decode() if last_position else "1970-01-01T00:00:00"

        rows = await self._execute_query(
            schema=table.schema_name,
            table_name=table.table_name,
            columns=table.columns,
            watermark_column=watermark_col,
            last_value=last_value,
            batch_size=batch_size,
        )

        events: list[ChangeEvent] = []
        max_watermark: str | None = None

        for row in rows[:batch_size]:
            # Fix 2.2: track the max watermark value in this batch.
            wm_val = row.get(watermark_col)
            if wm_val is not None:
                wm_str = str(wm_val)
                if max_watermark is None or wm_str > max_watermark:
                    max_watermark = wm_str

            # Fix 2.1: detect soft-deleted rows and emit DELETE events.
            if table.soft_delete_column and row.get(table.soft_delete_column):
                events.append(
                    ChangeEvent(
                        table_schema=table.schema_name,
                        table_name=table.table_name,
                        operation=ChangeOperation.DELETE,
                        before_values=dict(row),  # carry full row for PK extraction
                        after_values=None,
                    )
                )
            else:
                events.append(
                    ChangeEvent(
                        table_schema=table.schema_name,
                        table_name=table.table_name,
                        operation=ChangeOperation.INSERT,
                        after_values=dict(row),
                    )
                )

        # Fix 2.2: use the actual max watermark as the new position so restarts
        # can resume from where we left off, not from the beginning.
        if max_watermark is not None:
            new_position: WatermarkPosition = WatermarkPosition.from_value(max_watermark)
        elif last_position is not None:
            new_position = WatermarkPosition.from_bytes(last_position)
        else:
            new_position = WatermarkPosition.from_value(last_value)

        return CaptureBatch(changes=events, new_position=new_position)  # type: ignore[arg-type]

    async def _execute_query(
        self,
        schema: str,
        table_name: str,
        columns: list[str],
        watermark_column: str,
        last_value: str,
        batch_size: int,
    ) -> list[dict[str, Any]]:
        """Execute the watermark polling query.

        Override in subclass for actual database access.
        Returns a list of row dicts.
        """
        return []

    async def take_snapshot(
        self,
        table: TableInfo,
        callback: Callable[[list[ChangeEvent]], Awaitable[None]],
        chunk_size: int = 10000,
    ) -> None:
        """Full table snapshot via keyset pagination on the watermark column.

        Fix 2.6: uses the last watermark value to advance the cursor (keyset
        pagination) instead of a fixed OFFSET that is always reset to "" and
        therefore re-scans from row 1 on every batch.
        """
        last_value: str = ""
        watermark_col = table.watermark_column or "modified"
        while True:
            rows = await self._execute_query(
                schema=table.schema_name,
                table_name=table.table_name,
                columns=table.columns,
                watermark_column=watermark_col,
                last_value=last_value,   # advances on each iteration (Fix 2.6)
                batch_size=chunk_size,
            )
            if not rows:
                break
            events = [
                ChangeEvent(
                    table_schema=table.schema_name,
                    table_name=table.table_name,
                    operation=ChangeOperation.INSERT,
                    after_values=dict(row),
                )
                for row in rows
            ]
            await callback(events)
            # Advance cursor to the last watermark value seen
            last_row_wm = rows[-1].get(watermark_col)
            if last_row_wm is not None:
                last_value = str(last_row_wm)
            if len(rows) < chunk_size:
                break
