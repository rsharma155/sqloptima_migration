"""
Module: infrastructure/sqlserver/sqlserver_pool.py
Purpose: Thread-safe connection pool for SQL Server via pyodbc.
         Wraps blocking pyodbc calls in run_in_executor so callers stay async-friendly.
         Fix 6.1: replaces ad-hoc single-connection creation with a bounded pool that
         recycles connections, avoids repeated login overhead, and caps concurrency.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import asyncio
from typing import Any

import pyodbc

from infrastructure.sqlserver.sqlserver_connector import SqlServerConnectionConfig
from shared.contracts.base_connector import DatabaseConnector
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


class SqlServerConnectionPool:
    """Bounded async-safe pool of pyodbc connections.

    All blocking pyodbc calls are dispatched to the default thread-pool executor
    so the asyncio event loop is never blocked.

    Usage::

        pool = SqlServerConnectionPool(config, pool_size=4)
        await pool.initialize()
        conn = await pool.acquire()
        try:
            # use conn ...
        finally:
            await pool.release(conn)
        await pool.close_all()
    """

    def __init__(
        self,
        config: SqlServerConnectionConfig,
        pool_size: int = 5,
    ) -> None:
        if pool_size < 1:
            raise ValueError(f"pool_size must be >= 1, got {pool_size}")
        self._config = config
        self._pool_size = pool_size
        self._pool: asyncio.Queue[pyodbc.Connection] = asyncio.Queue(maxsize=pool_size)
        self._connections: list[pyodbc.Connection] = []
        self._initialized = False

    async def initialize(self) -> None:
        """Open all pool connections. Must be called before acquire()."""
        if self._initialized:
            return
        loop = asyncio.get_running_loop()
        conn_str = self._config.connection_string

        async def _open_one() -> pyodbc.Connection:
            return await loop.run_in_executor(None, pyodbc.connect, conn_str)

        self._connections = list(await asyncio.gather(*[_open_one() for _ in range(self._pool_size)]))
        for conn in self._connections:
            self._pool.put_nowait(conn)
        self._initialized = True
        logger.info("sqlserver_pool_initialized", pool_size=self._pool_size, host=self._config.host)

    async def acquire(self) -> pyodbc.Connection:
        """Borrow a connection from the pool. Blocks until one is available."""
        return await self._pool.get()

    async def release(self, conn: pyodbc.Connection) -> None:
        """Return a connection to the pool."""
        await self._pool.put(conn)

    async def close_all(self) -> None:
        """Close all pooled connections and drain the queue."""
        loop = asyncio.get_running_loop()
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                await loop.run_in_executor(None, conn.close)
            except asyncio.QueueEmpty:
                break
        self._connections.clear()
        self._initialized = False
        logger.info("sqlserver_pool_closed", host=self._config.host)

    @property
    def pool_size(self) -> int:
        return self._pool_size


class PooledSqlServerConnector(DatabaseConnector):
    """DatabaseConnector that borrows from a SqlServerConnectionPool.

    Fix 6.1: this connector wraps the pool so callers can use it anywhere
    a DatabaseConnector is expected, without knowing about the pool internals.
    Each execute() call acquires a connection, runs the query, then releases.
    """

    def __init__(
        self,
        config: SqlServerConnectionConfig,
        pool_size: int = 5,
    ) -> None:
        self._config = config
        self._pool_obj = SqlServerConnectionPool(config, pool_size=pool_size)

    async def connect(self) -> None:
        await self._pool_obj.initialize()

    async def disconnect(self) -> None:
        await self._pool_obj.close_all()

    async def execute(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        loop = asyncio.get_running_loop()
        conn = await self._pool_obj.acquire()
        try:
            def _sync() -> list[dict[str, Any]]:
                cursor = conn.cursor()
                if params:
                    cursor.execute(query, tuple(params.values()))
                else:
                    cursor.execute(query)
                if cursor.description is None:
                    return []
                cols = [col[0] for col in cursor.description]
                return [dict(zip(cols, row, strict=False)) for row in cursor.fetchall()]
            return await loop.run_in_executor(None, _sync)
        except Exception:
            raise
        finally:
            await self._pool_obj.release(conn)

    async def execute_many(self, query: str, params_list: list[dict[str, Any]]) -> None:
        loop = asyncio.get_running_loop()
        conn = await self._pool_obj.acquire()
        try:
            def _sync() -> None:
                cursor = conn.cursor()
                cursor.executemany(query, [tuple(p.values()) for p in params_list])
                conn.commit()
            await loop.run_in_executor(None, _sync)
        finally:
            await self._pool_obj.release(conn)
