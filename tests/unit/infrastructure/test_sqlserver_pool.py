"""
Module: test_sqlserver_pool.py
Purpose: TDD tests for item 6.1 — SqlServerConnectionPool and PooledSqlServerConnector.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from infrastructure.sqlserver.sqlserver_connector import SqlServerConnectionConfig
from infrastructure.sqlserver.sqlserver_pool import (
    PooledSqlServerConnector,
    SqlServerConnectionPool,
)


def _make_config(**overrides) -> SqlServerConnectionConfig:
    defaults = {
        "host": "localhost",
        "port": 1433,
        "database": "testdb",
        "username": "sa",
        "password": "Test@123",
    }
    defaults.update(overrides)
    return SqlServerConnectionConfig(**defaults)


def _make_mock_pyodbc_conn(rows=None, columns=None):
    cursor = MagicMock()
    cursor.description = (
        [(c, None, None, None, None, None, None) for c in (columns or [])]
        if columns
        else None
    )
    cursor.fetchall.return_value = rows or []
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


class TestSqlServerConnectionPool:
    """Unit tests for SqlServerConnectionPool."""

    @pytest.mark.asyncio
    async def test_initialize_creates_pool_size_connections(self):
        """initialize() must create exactly pool_size pyodbc connections."""
        config = _make_config()
        pool = SqlServerConnectionPool(config, pool_size=3)

        mock_conns = [MagicMock() for _ in range(3)]
        conn_iter = iter(mock_conns)

        with patch("infrastructure.sqlserver.sqlserver_pool.pyodbc.connect", side_effect=lambda cs: next(conn_iter)):
            await pool.initialize()

        assert pool._pool.qsize() == 3

    @pytest.mark.asyncio
    async def test_acquire_removes_connection_from_pool(self):
        """acquire() must return a connection and reduce pool size by one."""
        config = _make_config()
        pool = SqlServerConnectionPool(config, pool_size=2)

        mock_conns = [MagicMock(), MagicMock()]
        conn_iter = iter(mock_conns)

        with patch("infrastructure.sqlserver.sqlserver_pool.pyodbc.connect", side_effect=lambda cs: next(conn_iter)):
            await pool.initialize()

        conn = await pool.acquire()
        assert conn is not None
        assert pool._pool.qsize() == 1

    @pytest.mark.asyncio
    async def test_release_returns_connection_to_pool(self):
        """release() must put the connection back, restoring pool size."""
        config = _make_config()
        pool = SqlServerConnectionPool(config, pool_size=2)

        mock_conns = [MagicMock(), MagicMock()]
        conn_iter = iter(mock_conns)

        with patch("infrastructure.sqlserver.sqlserver_pool.pyodbc.connect", side_effect=lambda cs: next(conn_iter)):
            await pool.initialize()

        conn = await pool.acquire()
        assert pool._pool.qsize() == 1
        await pool.release(conn)
        assert pool._pool.qsize() == 2

    @pytest.mark.asyncio
    async def test_close_all_closes_every_connection(self):
        """close_all() must call .close() on each pooled connection."""
        config = _make_config()
        pool = SqlServerConnectionPool(config, pool_size=3)

        mock_conns = [MagicMock() for _ in range(3)]
        conn_iter = iter(mock_conns)

        with patch("infrastructure.sqlserver.sqlserver_pool.pyodbc.connect", side_effect=lambda cs: next(conn_iter)):
            await pool.initialize()

        await pool.close_all()
        for mc in mock_conns:
            mc.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_pool_empty_after_close_all(self):
        """Pool queue must be empty after close_all()."""
        config = _make_config()
        pool = SqlServerConnectionPool(config, pool_size=2)

        mock_conns = [MagicMock(), MagicMock()]
        conn_iter = iter(mock_conns)

        with patch("infrastructure.sqlserver.sqlserver_pool.pyodbc.connect", side_effect=lambda cs: next(conn_iter)):
            await pool.initialize()

        await pool.close_all()
        assert pool._pool.empty()

    @pytest.mark.asyncio
    async def test_concurrent_acquires_each_get_separate_connection(self):
        """Concurrent acquire() calls must each get a distinct connection."""
        config = _make_config()
        pool_size = 4
        pool = SqlServerConnectionPool(config, pool_size=pool_size)

        mock_conns = [MagicMock() for _ in range(pool_size)]
        conn_iter = iter(mock_conns)

        with patch("infrastructure.sqlserver.sqlserver_pool.pyodbc.connect", side_effect=lambda cs: next(conn_iter)):
            await pool.initialize()

        acquired = await asyncio.gather(*[pool.acquire() for _ in range(pool_size)])
        assert len(set(id(c) for c in acquired)) == pool_size


class TestPooledSqlServerConnector:
    """Unit tests for PooledSqlServerConnector (wraps SqlServerConnectionPool)."""

    @pytest.mark.asyncio
    async def test_connect_initializes_pool(self):
        """connect() must initialize the underlying pool."""
        config = _make_config()
        connector = PooledSqlServerConnector(config, pool_size=2)

        with patch.object(connector._pool_obj, "initialize", new=AsyncMock()) as mock_init:
            await connector.connect()
            mock_init.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_closes_all_pool_connections(self):
        """disconnect() must drain and close all pool connections."""
        config = _make_config()
        connector = PooledSqlServerConnector(config, pool_size=2)

        with patch.object(connector._pool_obj, "close_all", new=AsyncMock()) as mock_close:
            await connector.disconnect()
            mock_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_acquires_and_releases_connection(self):
        """execute() must acquire a connection, run the query, then release it."""
        config = _make_config()
        connector = PooledSqlServerConnector(config, pool_size=1)

        mock_conn, mock_cursor = _make_mock_pyodbc_conn(
            rows=[(42,)], columns=["val"]
        )

        acquire_calls = []
        release_calls = []

        async def fake_acquire():
            acquire_calls.append(True)
            return mock_conn

        async def fake_release(conn):
            release_calls.append(conn)

        connector._pool_obj.acquire = fake_acquire
        connector._pool_obj.release = fake_release

        result = await connector.execute("SELECT 42 AS val")

        assert len(acquire_calls) == 1
        assert len(release_calls) == 1
        assert result == [{"val": 42}]

    @pytest.mark.asyncio
    async def test_execute_releases_connection_on_error(self):
        """execute() must release the connection even when the query raises."""
        config = _make_config()
        connector = PooledSqlServerConnector(config, pool_size=1)

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.execute.side_effect = Exception("DB error")

        release_calls = []

        async def fake_acquire():
            return mock_conn

        async def fake_release(conn):
            release_calls.append(conn)

        connector._pool_obj.acquire = fake_acquire
        connector._pool_obj.release = fake_release

        with pytest.raises(Exception, match="DB error"):
            await connector.execute("SELECT 1")

        assert len(release_calls) == 1

    @pytest.mark.asyncio
    async def test_execute_with_params_passes_positional_args(self):
        """execute() with params dict must pass values as positional args to cursor."""
        config = _make_config()
        connector = PooledSqlServerConnector(config, pool_size=1)

        mock_conn, mock_cursor = _make_mock_pyodbc_conn(rows=[], columns=[])
        mock_cursor.description = None

        async def fake_acquire():
            return mock_conn

        async def fake_release(conn):
            pass

        connector._pool_obj.acquire = fake_acquire
        connector._pool_obj.release = fake_release

        await connector.execute("SELECT ? AS x", {"x": 99})
        mock_cursor.execute.assert_called_once_with("SELECT ? AS x", (99,))
