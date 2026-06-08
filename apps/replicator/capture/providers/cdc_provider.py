"""
Module: apps/replicator/capture/providers/cdc_provider.py
Purpose: Fix F.1 — SqlServerCdcProvider reads SQL Server CDC change tables
         via fn_cdc_get_all_changes_* and maps raw rows to ChangeEvent objects.
         Parses LSN bytes, maps operation codes (1=DELETE, 2=INSERT, 3=UPDATE-before,
         4=UPDATE-after) and discards UPDATE-before rows (op=3) since we only need
         the post-image for idempotent apply.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import struct
from typing import Any, Callable, Awaitable

from apps.replicator.capture.models import (
    CaptureBatch,
    ChangeEvent,
    ChangeOperation,
    LsnPosition,
    TableInfo,
)
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

# CDC operation codes from sys.fn_cdc_get_all_changes_*
_OP_DELETE = 1
_OP_INSERT = 2
_OP_UPDATE_BEFORE = 3
_OP_UPDATE_AFTER = 4

_CDC_META_COLS = {"__$start_lsn", "__$end_lsn", "__$seqval", "__$operation", "__$update_mask"}


def _parse_lsn(raw: bytes) -> LsnPosition:
    seg1, seg2, seg3 = struct.unpack(">III", raw)
    return LsnPosition(seg1, seg2, seg3)


class SqlServerCdcProvider:
    """Polls SQL Server CDC change tables and yields ChangeEvent batches.

    Fix F.1: CDC events were not wired up. This class bridges the gap between
    the polling loop in CaptureAgent and the raw CDC tables exposed by
    sys.fn_cdc_get_all_changes_<capture_instance>.

    LSN advancement contract:
    - When last_position is None: starts from fn_cdc_get_min_lsn(capture_instance).
    - When last_position is provided: uses it as the from-LSN, skipping the min-LSN call.
    - The returned CaptureBatch.new_position is the LSN of the last row in the batch
      (or max_lsn if the batch is empty).
    """

    def __init__(self, connector: Any) -> None:
        self._connector = connector
        self._connection_string: str = ""

    async def connect(self, connection_string: str) -> None:
        if not connection_string:
            raise ValueError("connection_string must not be empty")
        self._connection_string = connection_string

    async def capture_changes(
        self,
        table: TableInfo,
        last_position: bytes | None,
        batch_size: int = 1000,
    ) -> CaptureBatch:
        """Poll for new CDC events since last_position.

        Returns an empty CaptureBatch (changes=[]) when there are no new rows;
        new_position will be set to the current max_lsn so the caller can advance.
        """
        capture_instance = table.capture_instance or f"{table.schema_name}_{table.table_name}"

        # Determine from-LSN
        if last_position is None:
            min_rows = await self._connector.execute(
                "SELECT sys.fn_cdc_get_min_lsn(?) AS min_lsn",
                {"capture_instance": capture_instance},
            )
            from_lsn_bytes: bytes = min_rows[0]["min_lsn"] if min_rows else b"\x00" * 12
        else:
            from_lsn_bytes = last_position

        max_rows = await self._connector.execute(
            "SELECT sys.fn_cdc_get_max_lsn() AS max_lsn"
        )
        to_lsn_bytes: bytes = max_rows[0]["max_lsn"] if max_rows else from_lsn_bytes

        # Query CDC change table
        columns = table.columns
        if not columns:
            columns = await self._load_captured_columns(capture_instance)
        col_list = ", ".join(f"[{c}]" for c in columns)
        query = (
            f"SELECT TOP {batch_size} "
            f"__$start_lsn, __$operation, __$update_mask, {col_list} "
            f"FROM cdc.fn_cdc_get_all_changes_{capture_instance}(?, ?, N'all') "
            f"ORDER BY __$start_lsn, __$seqval"
        )
        rows = await self._connector.execute(
            query,
            {"from_lsn": from_lsn_bytes, "to_lsn": to_lsn_bytes},
        )

        changes: list[ChangeEvent] = []
        last_lsn_bytes = to_lsn_bytes
        for row in rows:
            op_code = row["__$operation"]
            lsn_raw = row["__$start_lsn"]
            last_lsn_bytes = lsn_raw

            # UPDATE-before row (op=3) contains the pre-image only; skip it.
            if op_code == _OP_UPDATE_BEFORE:
                continue

            data = {k: v for k, v in row.items() if k not in _CDC_META_COLS}

            if op_code == _OP_INSERT:
                event = ChangeEvent(
                    table_schema=table.schema_name,
                    table_name=table.table_name,
                    operation=ChangeOperation.INSERT,
                    after_values=data,
                    before_values=None,
                    lsn=_parse_lsn(lsn_raw),
                )
            elif op_code == _OP_DELETE:
                event = ChangeEvent(
                    table_schema=table.schema_name,
                    table_name=table.table_name,
                    operation=ChangeOperation.DELETE,
                    after_values=None,
                    before_values=data,
                    lsn=_parse_lsn(lsn_raw),
                )
            elif op_code == _OP_UPDATE_AFTER:
                event = ChangeEvent(
                    table_schema=table.schema_name,
                    table_name=table.table_name,
                    operation=ChangeOperation.UPDATE,
                    after_values=data,
                    before_values=None,
                    lsn=_parse_lsn(lsn_raw),
                )
            else:
                continue

            changes.append(event)

        new_position = _parse_lsn(last_lsn_bytes)
        logger.debug(
            "cdc_batch_captured",
            table=table.qualified_name,
            changes=len(changes),
            new_position=str(new_position),
        )
        return CaptureBatch(changes=changes, new_position=new_position)

    async def discover_tables(self, schema: str) -> list[TableInfo]:
        """Return all CDC-enabled tables in the given schema."""
        rows = await self._connector.execute(
            """
            SELECT s.name AS schema_name, t.name AS table_name, ct.capture_instance
            FROM cdc.change_tables ct
            JOIN sys.tables t ON t.object_id = ct.source_object_id
            JOIN sys.schemas s ON s.schema_id = t.schema_id
            WHERE s.name = ?
            """,
            {"schema": schema},
        )
        tables: list[TableInfo] = []
        for row in rows:
            capture_instance = row["capture_instance"]
            columns = await self._load_captured_columns(capture_instance)
            pk_columns = await self._load_pk_columns(row["schema_name"], row["table_name"])
            tables.append(
                TableInfo(
                    schema_name=row["schema_name"],
                    table_name=row["table_name"],
                    columns=columns,
                    pk_columns=pk_columns,
                    capture_instance=capture_instance,
                ),
            )
        return tables

    async def _load_captured_columns(self, capture_instance: str) -> list[str]:
        rows = await self._connector.execute(
            """
            SELECT cc.name AS column_name
            FROM cdc.change_tables ct
            JOIN cdc.captured_columns cc ON cc.object_id = ct.object_id
            WHERE ct.capture_instance = ?
            ORDER BY cc.column_id
            """,
            {"capture_instance": capture_instance},
        )
        return [str(r["column_name"]) for r in rows]

    async def _load_pk_columns(self, schema: str, table: str) -> list[str]:
        rows = await self._connector.execute(
            """
            SELECT c.name AS column_name
            FROM sys.key_constraints kc
            JOIN sys.index_columns ic
              ON ic.object_id = kc.parent_object_id AND ic.index_id = kc.unique_index_id
            JOIN sys.columns c
              ON c.object_id = ic.object_id AND c.column_id = ic.column_id
            WHERE kc.type = 'PK'
              AND kc.parent_object_id = OBJECT_ID(?)
            ORDER BY ic.key_ordinal
            """,
            {"full_name": f"{schema}.{table}"},
        )
        pk = [str(r["column_name"]) for r in rows]
        return pk if pk else ["id"]

    async def take_snapshot(
        self,
        table: TableInfo,
        callback: Callable[[list[ChangeEvent]], Awaitable[None]],
        chunk_size: int = 10_000,
    ) -> None:
        """Emit all current rows as INSERT ChangeEvents via callback."""
        col_list = ", ".join(f"[{c}]" for c in table.columns) if table.columns else "*"
        offset = 0
        while True:
            rows = await self._connector.execute(
                f"SELECT {col_list} FROM [{table.schema_name}].[{table.table_name}] "
                f"ORDER BY (SELECT NULL) OFFSET {offset} ROWS FETCH NEXT {chunk_size} ROWS ONLY"
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
            offset += len(rows)
            if len(rows) < chunk_size:
                break
