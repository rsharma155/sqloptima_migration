"""Tests for LOB streaming module.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from unittest.mock import AsyncMock

import pytest

from domains.migration.lob_streamer import LobInfo, LobMigrationResult, LobStreamConfig, LobStreamer


class TestLobInfo:
    def test_create_text_lob(self):
        info = LobInfo(column_name="description", data_type="NTEXT")
        assert info.is_binary is False
        assert info.column_name == "description"

    def test_create_binary_lob(self):
        info = LobInfo(column_name="photo", data_type="IMAGE")
        assert info.is_binary is True


class TestLobMigrationResult:
    def test_create(self):
        r = LobMigrationResult(column_name="data")
        assert r.success is True
        assert r.total_size_bytes == 0


class TestLobStreamConfig:
    def test_defaults(self):
        c = LobStreamConfig()
        assert c.chunk_size_bytes == 1048576
        assert c.max_buffer_size == 10485760


class TestLobStreamer:
    @pytest.fixture
    def streamer(self):
        return LobStreamer()

    @pytest.mark.asyncio
    async def test_stream_text_lob(self, streamer):
        call_count = [0]
        async def source_execute(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return [{"id": 1, "notes": "Hello World"}, {"id": 2, "notes": None}]
            return []

        mock_source = AsyncMock()
        mock_source.execute.side_effect = source_execute
        mock_target = AsyncMock()
        mock_target.execute.return_value = []

        info = LobInfo(column_name="notes", data_type="NTEXT")
        result = await streamer.stream_lob_column(
            mock_source, mock_target, "dbo", "users", info, "id"
        )
        assert result.success is True
        assert result.chunks_streamed == 1
        assert result.total_size_bytes == 11

    @pytest.mark.asyncio
    async def test_stream_binary_lob(self, streamer):
        call_count = [0]
        async def source_execute(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return [{"id": 1, "photo": b"\x00\x01\x02\x03"}]
            return []

        mock_source = AsyncMock()
        mock_source.execute.side_effect = source_execute
        mock_target = AsyncMock()

        info = LobInfo(column_name="photo", data_type="IMAGE", is_binary=True)
        result = await streamer.stream_lob_column(
            mock_source, mock_target, "dbo", "files", info, "id"
        )
        assert result.success is True
        assert result.chunks_streamed == 1
        assert result.total_size_bytes == 4

    @pytest.mark.asyncio
    async def test_stream_empty(self, streamer):
        mock_source = AsyncMock()
        mock_source.execute.return_value = []
        mock_target = AsyncMock()

        info = LobInfo(column_name="data", data_type="TEXT")
        result = await streamer.stream_lob_column(
            mock_source, mock_target, "dbo", "empty", info, "id"
        )
        assert result.success is True
        assert result.chunks_streamed == 0

    @pytest.mark.asyncio
    async def test_handles_error(self, streamer):
        mock_source = AsyncMock()
        mock_source.execute.side_effect = Exception("Connection error")
        mock_target = AsyncMock()

        info = LobInfo(column_name="data", data_type="TEXT")
        result = await streamer.stream_lob_column(
            mock_source, mock_target, "dbo", "failing", info, "id"
        )
        assert result.success is False
        assert result.error is not None


class TestLobStreamerIdentifierValidation:
    """Injection-prevention: all SQL identifier arguments must be validated."""

    @pytest.fixture
    def streamer(self):
        return LobStreamer()

    @pytest.mark.asyncio
    async def test_rejects_injection_in_schema(self, streamer):
        mock_source = AsyncMock()
        mock_target = AsyncMock()
        info = LobInfo(column_name="data", data_type="TEXT")
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            await streamer.stream_lob_column(
                mock_source, mock_target, "dbo; DROP TABLE users--", "t", info, "id"
            )

    @pytest.mark.asyncio
    async def test_rejects_injection_in_table(self, streamer):
        mock_source = AsyncMock()
        mock_target = AsyncMock()
        info = LobInfo(column_name="data", data_type="TEXT")
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            await streamer.stream_lob_column(
                mock_source, mock_target, "dbo", "users; DELETE FROM users--", info, "id"
            )

    @pytest.mark.asyncio
    async def test_rejects_injection_in_key_column(self, streamer):
        mock_source = AsyncMock()
        mock_target = AsyncMock()
        info = LobInfo(column_name="data", data_type="TEXT")
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            await streamer.stream_lob_column(
                mock_source, mock_target, "dbo", "users", info, "id; DROP TABLE--"
            )

    @pytest.mark.asyncio
    async def test_rejects_injection_in_column_name(self, streamer):
        mock_source = AsyncMock()
        mock_target = AsyncMock()
        info = LobInfo(column_name="col' OR '1'='1", data_type="TEXT")
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            await streamer.stream_lob_column(
                mock_source, mock_target, "dbo", "users", info, "id"
            )

    @pytest.mark.asyncio
    async def test_detect_lob_columns_rejects_injection(self, streamer):
        mock_conn = AsyncMock()
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            await LobStreamer.detect_lob_columns(mock_conn, "dbo; DROP TABLE--", "users")
