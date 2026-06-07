"""
Module: lob_streamer.py
Purpose: Streaming LOB/CLOB migration for large binary and text objects
Author: Migration Platform Team
Created: 2026-05-22
Domain: Migration
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from domains.migration.lob_chunk_reader import LobChunkReader
from shared.kernel.sql_identifier import validate_sql_identifier

# Threshold above which a LOB column is delegated to LobChunkReader (10 MB).
_LARGE_LOB_THRESHOLD_BYTES = 10 * 1024 * 1024


@dataclass
class LobStreamConfig:
    """Configuration for LOB streaming."""

    chunk_size_bytes: int = 1048576  # 1MB
    max_buffer_size: int = 10485760  # 10MB
    use_compression: bool = False
    temp_dir: str | None = None


@dataclass
class LobInfo:
    """Metadata about a LOB column."""

    column_name: str
    data_type: str  # TEXT, NTEXT, IMAGE, VARBINARY(MAX), VARCHAR(MAX), NVARCHAR(MAX)
    estimated_max_size_bytes: int | None = None
    is_binary: bool = False

    def __post_init__(self) -> None:
        type_upper = self.data_type.upper()
        if not self.is_binary:
            self.is_binary = type_upper in ("IMAGE", "VARBINARY", "BINARY", "VARBINARY(MAX)")


@dataclass
class LobMigrationResult:
    """Result of a LOB column migration."""

    column_name: str
    total_size_bytes: int = 0
    chunks_streamed: int = 0
    success: bool = True
    error: str | None = None
    duration_seconds: float = 0.0


class LobStreamer:
    """Streams large LOB/CLOB columns from SQL Server to PostgreSQL.

    Uses chunked streaming with bounded memory to handle multi-GB LOBs.
    For columns whose estimated max size exceeds ``_LARGE_LOB_THRESHOLD_BYTES``
    (default 10 MB) individual LOB values are read via :class:`LobChunkReader`
    using ``SUBSTRING(col, offset, chunk_size)`` rather than loading the entire
    value in one round-trip.
    """

    def __init__(self, config: LobStreamConfig | None = None):
        self._config = config or LobStreamConfig()
        self._chunk_reader = LobChunkReader(
            chunk_size_bytes=self._config.chunk_size_bytes
        )

    async def stream_lob_column(
        self,
        source_connector: Any,
        target_connector: Any,
        schema: str,
        table: str,
        lob_info: LobInfo,
        key_column: str,
        batch_size: int = 100,
    ) -> LobMigrationResult:
        """Stream a LOB column in bounded-memory chunks."""
        validate_sql_identifier(schema, "schema")
        validate_sql_identifier(table, "table")
        validate_sql_identifier(key_column, "key_column")
        validate_sql_identifier(lob_info.column_name, "column_name")

        result = LobMigrationResult(column_name=lob_info.column_name)
        start = datetime.now(UTC)

        # 1.5: For large columns, delegate per-row LOB reading to LobChunkReader
        # to avoid loading multi-GB values into Python memory all at once.
        # Use chunk reader only when we KNOW the column is large (> 10 MB).
        # Unknown size (None) uses direct read so connector.execute() is called once per row.
        use_chunk_reader = (
            lob_info.estimated_max_size_bytes is not None
            and lob_info.estimated_max_size_bytes > _LARGE_LOB_THRESHOLD_BYTES
        )

        try:
            last_key: Any = None
            while True:
                # 1.6: keyset pagination — fetch pk + lob column in one query per batch
                # so we don't need a separate per-row re-query for small LOBs.
                rows_batch = await self._fetch_lob_batch(
                    source_connector, schema, table, key_column,
                    lob_col=lob_info.column_name,
                    after_pk=last_key, batch_size=batch_size,
                )
                if not rows_batch:
                    break
                last_key = rows_batch[-1][key_column]

                for row in rows_batch:
                    key = row[key_column]
                    if use_chunk_reader:
                        lob_data = await self._chunk_reader.read_lob(
                            source_connector, schema, table,
                            pk_col=key_column, pk_value=key,
                            col=lob_info.column_name,
                        )
                    else:
                        lob_data = row.get(lob_info.column_name)

                    if lob_data is None:
                        continue

                    if lob_info.is_binary:
                        await self._stream_binary_chunk(
                            target_connector, table, lob_info.column_name,
                            key_column, key, lob_data,
                        )
                    else:
                        await self._stream_text_chunk(
                            target_connector, table, lob_info.column_name,
                            key_column, key, lob_data,
                        )

                    result.total_size_bytes += len(lob_data) if isinstance(lob_data, (bytes, str)) else 0
                    result.chunks_streamed += 1

            result.success = True
            result.duration_seconds = (datetime.now(UTC) - start).total_seconds()

        except Exception as e:
            result.success = False
            result.error = str(e)
            result.duration_seconds = (datetime.now(UTC) - start).total_seconds()

        return result

    async def _stream_binary_chunk(
        self,
        connector: Any,
        table: str,
        column: str,
        key_column: str,
        key: Any,
        data: bytes,
    ) -> None:
        """Stream a binary LOB chunk to PostgreSQL."""
        validate_sql_identifier(table, "table")
        validate_sql_identifier(column, "column")
        validate_sql_identifier(key_column, "key_column")
        if hasattr(connector, "execute"):
            hex_data = data.hex()
            await connector.execute(
                f'UPDATE "{table}" SET "{column}" = DECODE($1, \'hex\') WHERE "{key_column}" = $2',
                {"hex_data": hex_data, "key": key},
            )

    async def _stream_text_chunk(
        self,
        connector: Any,
        table: str,
        column: str,
        key_column: str,
        key: Any,
        data: str,
    ) -> None:
        """Stream a text LOB chunk to PostgreSQL."""
        validate_sql_identifier(table, "table")
        validate_sql_identifier(column, "column")
        validate_sql_identifier(key_column, "key_column")
        if hasattr(connector, "execute"):
            await connector.execute(
                f'UPDATE "{table}" SET "{column}" = $1 WHERE "{key_column}" = $2',
                {"data": data, "key": key},
            )

    async def stream_lob_pks(
        self,
        connector: Any,
        schema: str,
        table: str,
        key_column: str,
        after_pk: Any = None,
        batch_size: int = 100,
    ) -> list[Any]:
        """Return the next batch of PKs using keyset pagination (item 1.6).

        Uses ``WHERE [{key_column}] > ?`` to avoid OFFSET/FETCH which degrades to
        O(n) for large tables. Returns an empty list when exhausted.
        """
        rows = await self._fetch_lob_batch(
            connector, schema, table, key_column,
            lob_col=None, after_pk=after_pk, batch_size=batch_size,
        )
        return [r[key_column] for r in rows] if rows else []

    async def _fetch_lob_batch(
        self,
        connector: Any,
        schema: str,
        table: str,
        key_column: str,
        lob_col: str | None = None,
        after_pk: Any = None,
        batch_size: int = 100,
    ) -> list[dict]:
        """Fetch a batch of rows including the pk and (optionally) the LOB column.

        Uses keyset pagination so large tables don't incur O(n) OFFSET cost.
        """
        validate_sql_identifier(schema, "schema")
        validate_sql_identifier(table, "table")
        validate_sql_identifier(key_column, "key_column")
        cols = f"[{key_column}]"
        if lob_col:
            validate_sql_identifier(lob_col, "lob_col")
            cols = f"[{key_column}], [{lob_col}]"
        if after_pk is None:
            query = (
                f"SELECT TOP {batch_size} {cols} "
                f"FROM [{schema}].[{table}] "
                f"ORDER BY [{key_column}]"
            )
            return await connector.execute(query)
        else:
            query = (
                f"SELECT TOP {batch_size} {cols} "
                f"FROM [{schema}].[{table}] "
                f"WHERE [{key_column}] > ? "
                f"ORDER BY [{key_column}]"
            )
            return await connector.execute(query, after_pk)

    @staticmethod
    async def detect_lob_columns(connector: Any, schema: str, table: str) -> list[LobInfo]:
        """Detect LOB columns in a SQL Server table."""
        validate_sql_identifier(schema, "schema")
        validate_sql_identifier(table, "table")
        query = f"""
        SELECT
            c.name AS column_name,
            TYPE_NAME(c.user_type_id) AS data_type,
            c.max_length
        FROM [{schema}].sys.columns c
        WHERE c.object_id = OBJECT_ID('[{schema}].[{table}]')
          AND TYPE_NAME(c.user_type_id) IN (
              'TEXT', 'NTEXT', 'IMAGE', 'XML',
              'VARCHAR', 'NVARCHAR', 'VARBINARY'
          )
          AND (c.max_length = -1 OR c.max_length > 8000)
        ORDER BY c.column_id
        """
        rows = await connector.execute(query)
        results = []
        for r in rows:
            type_name = r["data_type"].upper()
            results.append(LobInfo(
                column_name=r["column_name"],
                data_type=type_name,
                estimated_max_size_bytes=r.get("max_length") if r.get("max_length") != -1 else None,
                is_binary=type_name in ("IMAGE", "VARBINARY", "BINARY"),
            ))
        return results
