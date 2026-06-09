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

import re
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
_CAPTURE_INSTANCE_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _quote_mssql_ident(name: str) -> str:
    """Bracket-quote a SQL Server identifier (``]`` doubled inside)."""
    return "[" + name.replace("]", "]]") + "]"


def _normalize_lsn_bytes(raw: Any) -> bytes | None:
    """Coerce pyodbc LSN values to exactly 10 big-endian bytes."""
    if raw is None:
        return None
    if isinstance(raw, memoryview):
        raw = raw.tobytes()
    elif isinstance(raw, bytearray):
        raw = bytes(raw)
    elif not isinstance(raw, bytes):
        return None
    if not raw:
        return None
    if len(raw) < 10:
        return raw.ljust(10, b"\x00")
    return raw[:10]


def _parse_lsn(raw: bytes) -> LsnPosition:
    normalized = _normalize_lsn_bytes(raw)
    if not normalized:
        return LsnPosition(0, 0, 0)
    # SQL Server LSN is 10 bytes: 4 bytes VLF seq, 4 bytes block offset, 2 bytes slot.
    seg1, seg2, seg3 = struct.unpack(">IIH", normalized)
    return LsnPosition(seg1, seg2, seg3)


class SqlServerCdcProvider:
    """Polls SQL Server CDC change tables and yields ChangeEvent batches.

    Fix F.1: CDC events were not wired up. This class bridges the gap between
    the polling loop in CaptureAgent and the raw CDC tables exposed by
    sys.fn_cdc_get_all_changes_<capture_instance>.

    LSN advancement contract:
    - Reads directly from ``cdc.<capture_instance>_CT`` (avoids the misleading TVF
      error 313 that SQL Server raises for out-of-range LSN windows).
    - When last_position is None: starts at ``fn_cdc_get_min_lsn`` (inclusive).
    - When last_position is provided: reads rows with ``__$start_lsn > last_position``.
    - Checkpoints behind CDC retention are clamped to the current min LSN.
    - The returned CaptureBatch.new_position is the last row LSN, or max_lsn when empty.
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
        capture_instance = await self._resolve_capture_instance(table)
        columns = await self._resolve_columns(table, capture_instance)
        col_list = ", ".join(_quote_mssql_ident(c) for c in columns)

        min_lsn = await self._fetch_min_lsn(capture_instance)
        max_lsn = await self._fetch_max_lsn()

        if max_lsn is None:
            logger.warning(
                "cdc_max_lsn_null",
                table=table.qualified_name,
                hint="SQL Server Agent may be stopped; CDC max LSN unavailable",
            )
            return CaptureBatch(changes=[], new_position=LsnPosition(0, 0, 0))

        if min_lsn is None:
            logger.debug("cdc_min_lsn_null", table=table.qualified_name)
            return CaptureBatch(changes=[], new_position=_parse_lsn(max_lsn))

        last_bytes = _normalize_lsn_bytes(last_position)
        if last_bytes is None:
            from_lsn_bytes = min_lsn
            compare_op = ">="
        elif last_bytes < min_lsn:
            logger.warning(
                "cdc_checkpoint_before_min_lsn",
                table=table.qualified_name,
                checkpoint=last_bytes.hex(),
                min_lsn=min_lsn.hex(),
            )
            from_lsn_bytes = min_lsn
            compare_op = ">="
        else:
            from_lsn_bytes = last_bytes
            compare_op = ">"

        if min_lsn > max_lsn or (compare_op == ">" and from_lsn_bytes >= max_lsn):
            return CaptureBatch(changes=[], new_position=_parse_lsn(max_lsn))

        change_table = f"cdc.{_quote_mssql_ident(capture_instance + '_CT')}"
        query = (
            f"SELECT TOP ({batch_size}) "
            f"__$start_lsn, __$operation, __$update_mask, {col_list} "
            f"FROM {change_table} "
            f"WHERE __$start_lsn {compare_op} ? "
            f"ORDER BY __$start_lsn, __$seqval"
        )
        rows = await self._connector.execute(query, from_lsn_bytes)

        changes: list[ChangeEvent] = []
        last_lsn_bytes = max_lsn
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

    async def _fetch_min_lsn(self, capture_instance: str) -> bytes | None:
        rows = await self._connector.execute(
            "SELECT sys.fn_cdc_get_min_lsn(?) AS min_lsn",
            capture_instance,
        )
        return _normalize_lsn_bytes(rows[0]["min_lsn"] if rows else None)

    async def _fetch_max_lsn(self) -> bytes | None:
        rows = await self._connector.execute(
            "SELECT sys.fn_cdc_get_max_lsn() AS max_lsn",
        )
        return _normalize_lsn_bytes(rows[0]["max_lsn"] if rows else None)

    async def _resolve_capture_instance(self, table: TableInfo) -> str:
        """Return the CDC capture instance for *table*, looking it up when needed."""
        if table.capture_instance:
            capture_instance = table.capture_instance
        else:
            rows = await self._connector.execute(
                """
                SELECT ct.capture_instance
                FROM cdc.change_tables ct
                JOIN sys.tables t ON t.object_id = ct.source_object_id
                JOIN sys.schemas s ON s.schema_id = t.schema_id
                WHERE s.name = ? AND t.name = ?
                """,
                table.schema_name,
                table.table_name,
            )
            if not rows:
                guessed = f"{table.schema_name}_{table.table_name}"
                raise ValueError(
                    f"CDC is not enabled for {table.qualified_name} "
                    f"(no capture instance found; expected e.g. {guessed!r})"
                )
            capture_instance = str(rows[0]["capture_instance"])

        if not _CAPTURE_INSTANCE_RE.fullmatch(capture_instance):
            raise ValueError(f"Invalid CDC capture instance name: {capture_instance!r}")
        return capture_instance

    async def _resolve_columns(self, table: TableInfo, capture_instance: str) -> list[str]:
        """Return captured column names, loading from CDC metadata when placeholders are used."""
        if table.columns and table.columns != ["*"] and "*" not in table.columns:
            return table.columns
        return await self._load_captured_columns(capture_instance)

    async def _load_captured_columns(self, capture_instance: str) -> list[str]:
        rows = await self._connector.execute(
            """
            SELECT cc.column_name
            FROM cdc.change_tables ct
            JOIN cdc.captured_columns cc ON cc.object_id = ct.object_id
            WHERE ct.capture_instance = ?
            ORDER BY cc.column_id
            """,
            capture_instance,
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
