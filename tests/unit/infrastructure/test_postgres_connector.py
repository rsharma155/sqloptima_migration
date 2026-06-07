"""
Module: tests/unit/infrastructure/test_postgres_connector.py
Purpose: Unit tests for PostgresConnector — focusing on the statement-timeout
         protection added in Issue #16 (a slow query must not be able to hang a
         pooled connection indefinitely).
Domain: Infrastructure
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from infrastructure.postgres.postgres_connector import (
    PostgresConnectionConfig,
    PostgresConnector,
)


class _FakeAcquire:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def __aenter__(self) -> Any:
        return self._conn

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class _FakePool:
    """Minimal stand-in for an asyncpg pool that yields a mock connection."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire(self._conn)


def _make_config(**overrides: Any) -> PostgresConnectionConfig:
    cfg = PostgresConnectionConfig(
        host="localhost", port=5432, database="db",
        username="u", password="pw",
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


@pytest.fixture
def mock_conn():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    return conn


class TestStatementTimeout:
    def test_config_has_default_statement_timeout(self):
        cfg = _make_config()
        assert cfg.statement_timeout_seconds > 0

    @pytest.mark.asyncio
    async def test_execute_passes_default_timeout_to_fetch(self, mock_conn):
        cfg = _make_config()
        connector = PostgresConnector(cfg)
        connector._pool = _FakePool(mock_conn)

        await connector.execute("SELECT 1")

        mock_conn.fetch.assert_awaited_once()
        _, kwargs = mock_conn.fetch.await_args
        assert kwargs.get("timeout") == cfg.statement_timeout_seconds

    @pytest.mark.asyncio
    async def test_execute_uses_configured_timeout(self, mock_conn):
        cfg = _make_config(statement_timeout_seconds=5.0)
        connector = PostgresConnector(cfg)
        connector._pool = _FakePool(mock_conn)

        await connector.execute("SELECT 1", {"id": 1})

        _, kwargs = mock_conn.fetch.await_args
        assert kwargs.get("timeout") == 5.0

    @pytest.mark.asyncio
    async def test_execute_raises_when_not_connected(self):
        connector = PostgresConnector(_make_config())
        with pytest.raises(RuntimeError, match="Not connected"):
            await connector.execute("SELECT 1")
