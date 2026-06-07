"""
Module: domains/migration/lob_chunk_reader.py
Purpose: Chunked LOB reading via SQL Server SUBSTRING() to avoid OOM on large blobs.
         Reads a single LOB value for a given PK in configurable byte-sized pieces,
         eliminating the need to materialise multi-GB values in Python memory.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from typing import Any

from shared.kernel.sql_identifier import validate_sql_identifier
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

_DEFAULT_CHUNK_SIZE_BYTES = 1024 * 1024  # 1 MB


class LobChunkReader:
    """Reads a single LOB/CLOB column value in bounded-memory chunks.

    Uses SQL Server's ``SUBSTRING(col, offset, chunk_size)`` to stream
    one LOB at a time, avoiding OOM for columns exceeding available RAM.

    Example::

        reader = LobChunkReader(chunk_size_bytes=1024 * 1024)
        data = await reader.read_lob(
            connector, "dbo", "files", "file_id", pk_value=42, col="content"
        )

    The *data* result is a ``bytes`` object assembled from all chunks, or
    a ``str`` if the database returned text chunks, or ``None`` if the column
    value is SQL NULL.
    """

    def __init__(self, chunk_size_bytes: int = _DEFAULT_CHUNK_SIZE_BYTES) -> None:
        self._chunk_size = chunk_size_bytes

    @property
    def chunk_size_bytes(self) -> int:
        return self._chunk_size

    async def read_lob(
        self,
        connector: Any,
        schema: str,
        table: str,
        pk_col: str,
        pk_value: Any,
        col: str,
    ) -> bytes | str | None:
        """Read *col* for the row identified by *pk_value* in chunks.

        Returns the fully assembled LOB value, or ``None`` if the column
        contains SQL NULL.

        Args:
            connector:  SQL Server connector with an ``execute(sql, params)``
                        method (parameterised; params as a dict or positional).
            schema:     SQL Server schema name (e.g. ``"dbo"``).
            table:      Table name.
            pk_col:     Primary-key column that uniquely identifies the row.
            pk_value:   The PK value used to filter the row (passed as a
                        query parameter — never string-interpolated).
            col:        LOB column name to read.

        Returns:
            Assembled ``bytes`` or ``str``, or ``None`` for a NULL column.
        """
        validate_sql_identifier(schema, "schema")
        validate_sql_identifier(table, "table")
        validate_sql_identifier(pk_col, "pk_col")
        validate_sql_identifier(col, "col")

        # SUBSTRING uses 1-based offsets in SQL Server / T-SQL.
        sql_offset = 1
        chunks_binary: list[bytes] = []
        chunks_text: list[str] = []
        is_binary: bool | None = None

        while True:
            query = (
                f"SELECT SUBSTRING([{col}], ?, ?) AS chunk "
                f"FROM [{schema}].[{table}] "
                f"WHERE [{pk_col}] = ?"
            )
            rows = await connector.execute(query, (sql_offset, self._chunk_size, pk_value))

            if not rows:
                break

            chunk = rows[0].get("chunk")

            # NULL column — signal that the entire LOB is NULL
            if chunk is None:
                if sql_offset == 1:
                    return None
                break

            # Empty bytes / empty string — SUBSTRING past end of value
            if isinstance(chunk, (bytes, bytearray)) and len(chunk) == 0:
                break
            if isinstance(chunk, str) and len(chunk) == 0:
                break

            if is_binary is None:
                is_binary = isinstance(chunk, (bytes, bytearray))

            if is_binary:
                chunks_binary.append(bytes(chunk))
            else:
                chunks_text.append(str(chunk))

            sql_offset += self._chunk_size

        if is_binary is None:
            # No data was ever returned (all None/empty at offset 1)
            return None

        if is_binary:
            return b"".join(chunks_binary)
        return "".join(chunks_text)
