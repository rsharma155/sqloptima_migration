"""
Module: tests/unit/test_lob_chunk_reader.py
Purpose: TDD tests for LobChunkReader — chunked reading of large LOBs via SUBSTRING
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from unittest.mock import AsyncMock, call

import pytest

from domains.migration.lob_chunk_reader import LobChunkReader


@pytest.fixture
def reader():
    return LobChunkReader(chunk_size_bytes=4)  # tiny chunk for tests


class TestLobChunkReaderDefaults:
    def test_default_chunk_size(self):
        r = LobChunkReader()
        assert r.chunk_size_bytes == 1024 * 1024  # 1 MB

    def test_custom_chunk_size(self):
        r = LobChunkReader(chunk_size_bytes=512 * 1024)
        assert r.chunk_size_bytes == 512 * 1024


class TestLobChunkReaderBinary:
    @pytest.mark.asyncio
    async def test_reads_single_chunk(self, reader):
        """Small LOB fits in one chunk."""
        connector = AsyncMock()
        # SUBSTRING query returns the data; second call returns empty
        connector.execute.side_effect = [
            [{"chunk": b"\x01\x02\x03"}],
            [{"chunk": None}],
        ]
        data = await reader.read_lob(connector, "dbo", "files", "id", pk_value=1, col="content")
        assert data == b"\x01\x02\x03"

    @pytest.mark.asyncio
    async def test_reads_multiple_chunks(self, reader):
        """LOB larger than chunk_size is assembled from multiple calls."""
        connector = AsyncMock()
        connector.execute.side_effect = [
            [{"chunk": b"\x01\x02\x03\x04"}],
            [{"chunk": b"\x05\x06\x07\x08"}],
            [{"chunk": None}],
        ]
        data = await reader.read_lob(connector, "dbo", "files", "id", pk_value=1, col="content")
        assert data == b"\x01\x02\x03\x04\x05\x06\x07\x08"

    @pytest.mark.asyncio
    async def test_returns_none_for_null_lob(self, reader):
        """First chunk returning None means the column is NULL."""
        connector = AsyncMock()
        connector.execute.return_value = [{"chunk": None}]
        data = await reader.read_lob(connector, "dbo", "files", "id", pk_value=1, col="content")
        assert data is None

    @pytest.mark.asyncio
    async def test_query_uses_substring_syntax(self, reader):
        """Verify the SUBSTRING(...) query is formed correctly."""
        connector = AsyncMock()
        connector.execute.side_effect = [
            [{"chunk": b"\xAB"}],
            [{"chunk": None}],
        ]
        await reader.read_lob(connector, "dbo", "blobs", "pk", pk_value=42, col="data")

        first_call = connector.execute.call_args_list[0]
        query_arg = first_call[0][0]
        assert "SUBSTRING" in query_arg
        assert "[data]" in query_arg
        assert "[blobs]" in query_arg
        assert "[dbo]" in query_arg
        assert "[pk]" in query_arg

    @pytest.mark.asyncio
    async def test_query_uses_parameterized_pk(self, reader):
        """PK value is passed as a query parameter, never interpolated into SQL."""
        connector = AsyncMock()
        connector.execute.side_effect = [
            [{"chunk": b"\x00"}],
            [{"chunk": None}],
        ]
        pk_value = 99
        await reader.read_lob(connector, "dbo", "t", "id", pk_value=pk_value, col="col")

        first_call = connector.execute.call_args_list[0]
        # SQL string should not contain the literal PK value
        query_str = first_call[0][0]
        assert str(pk_value) not in query_str

    @pytest.mark.asyncio
    async def test_handles_empty_bytes_chunk(self, reader):
        """Empty bytes (b'') returned by SUBSTRING signals end of LOB."""
        connector = AsyncMock()
        connector.execute.side_effect = [
            [{"chunk": b"\xFF"}],
            [{"chunk": b""}],
        ]
        data = await reader.read_lob(connector, "dbo", "t", "id", pk_value=1, col="col")
        assert data == b"\xFF"


class TestLobChunkReaderText:
    @pytest.mark.asyncio
    async def test_reads_text_lob(self, reader):
        connector = AsyncMock()
        connector.execute.side_effect = [
            [{"chunk": "Hell"}],
            [{"chunk": "o Wo"}],
            [{"chunk": "rld"}],
            [{"chunk": None}],
        ]
        data = await reader.read_lob(connector, "dbo", "docs", "id", pk_value=7, col="body")
        assert data == "Hell" + "o Wo" + "rld"

    @pytest.mark.asyncio
    async def test_mixed_none_stops_iteration(self, reader):
        connector = AsyncMock()
        connector.execute.side_effect = [
            [{"chunk": "abc"}],
            [{"chunk": None}],
        ]
        data = await reader.read_lob(connector, "dbo", "docs", "id", pk_value=7, col="body")
        assert data == "abc"
