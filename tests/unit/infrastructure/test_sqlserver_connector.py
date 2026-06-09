# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""Unit tests for SqlServerConnector.

TDD contract (L-8):
- connect(), execute(), and execute_many() must NEVER call asyncio.get_event_loop()
  inside an async context — they must use asyncio.get_running_loop().
- All blocking pyodbc calls must be dispatched via run_in_executor so the async
  event loop is never stalled.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from infrastructure.sqlserver.sqlserver_connector import (
    SqlServerConnectionConfig,
    SqlServerConnector,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**overrides: Any) -> SqlServerConnectionConfig:
    defaults: dict[str, Any] = {
        "host": "localhost",
        "port": 1433,
        "database": "testdb",
        "username": "sa",
        "password": "Test@123",
    }
    defaults.update(overrides)
    return SqlServerConnectionConfig(**defaults)


def _make_mock_connection(rows: list[tuple] = None, columns: list[str] = None):
    """Return a mock pyodbc connection + cursor pair."""
    mock_cursor = MagicMock()
    mock_cursor.description = (
        [(col, None, None, None, None, None, None) for col in (columns or [])]
        if columns
        else None
    )
    mock_cursor.nextset.return_value = False
    mock_cursor.fetchall.return_value = rows or []

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn, mock_cursor


# ---------------------------------------------------------------------------
# L-8: asyncio.get_event_loop() must NOT be called inside async methods
# ---------------------------------------------------------------------------

class TestNoGetEventLoopInsideAsync:
    """Ensure all async methods use get_running_loop(), not get_event_loop()."""

    async def test_connect_does_not_call_get_event_loop(self):
        config = _make_config()
        connector = SqlServerConnector(config)
        mock_conn, _ = _make_mock_connection()

        get_event_loop_calls: list[str] = []

        original_get_event_loop = asyncio.get_event_loop

        def spy_get_event_loop():
            get_event_loop_calls.append("get_event_loop called")
            return original_get_event_loop()

        with (
            patch("infrastructure.sqlserver.sqlserver_connector.asyncio.get_event_loop", spy_get_event_loop),
            patch("pyodbc.connect", return_value=mock_conn),
        ):
            await connector.connect()

        assert get_event_loop_calls == [], (
            "connect() must not call asyncio.get_event_loop() inside an async context; "
            "use asyncio.get_running_loop() instead"
        )

    async def test_execute_does_not_call_get_event_loop(self):
        config = _make_config()
        connector = SqlServerConnector(config)
        mock_conn, mock_cursor = _make_mock_connection(
            rows=[(1, "Alice")], columns=["id", "name"]
        )
        connector._connection = mock_conn
        connector._cursor = mock_cursor

        get_event_loop_calls: list[str] = []
        original = asyncio.get_event_loop

        def spy():
            get_event_loop_calls.append("called")
            return original()

        with patch("infrastructure.sqlserver.sqlserver_connector.asyncio.get_event_loop", spy):
            await connector.execute("SELECT id, name FROM users")

        assert get_event_loop_calls == [], (
            "execute() must not call asyncio.get_event_loop()"
        )

    async def test_execute_many_does_not_call_get_event_loop(self):
        config = _make_config()
        connector = SqlServerConnector(config)
        mock_conn, mock_cursor = _make_mock_connection()
        connector._connection = mock_conn
        connector._cursor = mock_cursor

        get_event_loop_calls: list[str] = []
        original = asyncio.get_event_loop

        def spy():
            get_event_loop_calls.append("called")
            return original()

        with patch("infrastructure.sqlserver.sqlserver_connector.asyncio.get_event_loop", spy):
            await connector.execute_many("INSERT INTO t VALUES (?)", [{"v": 1}])

        assert get_event_loop_calls == [], (
            "execute_many() must not call asyncio.get_event_loop()"
        )


# ---------------------------------------------------------------------------
# Functional: blocking calls run in executor
# ---------------------------------------------------------------------------

class TestExecutorDispatch:
    """Verify that blocking pyodbc ops are sent to run_in_executor."""

    async def test_connect_dispatches_pyodbc_connect_to_executor(self):
        config = _make_config()
        connector = SqlServerConnector(config)
        mock_conn, _ = _make_mock_connection()
        loop = asyncio.get_running_loop()
        executor_calls: list[Any] = []

        original_run = loop.run_in_executor

        async def spy_executor(executor, func, *args):
            executor_calls.append(func)
            return await original_run(executor, func, *args)

        with (
            patch.object(loop, "run_in_executor", spy_executor),
            patch("pyodbc.connect", return_value=mock_conn),
        ):
            with patch(
                "infrastructure.sqlserver.sqlserver_connector.asyncio.get_running_loop",
                return_value=loop,
            ):
                await connector.connect()

        assert len(executor_calls) >= 1, "connect() must dispatch at least one call to run_in_executor"

    async def test_execute_returns_mapped_rows(self):
        config = _make_config()
        connector = SqlServerConnector(config)
        mock_conn, mock_cursor = _make_mock_connection(
            rows=[(42, "Bob")], columns=["id", "name"]
        )
        connector._connection = mock_conn
        connector._cursor = mock_cursor

        rows = await connector.execute("SELECT id, name FROM users")

        assert rows == [{"id": 42, "name": "Bob"}]

    async def test_execute_advances_past_declare_to_select_result_set(self):
        """DECLARE batches expose the SELECT rowset only after nextset()."""
        config = _make_config()
        connector = SqlServerConnector(config)
        mock_conn, mock_cursor = _make_mock_connection(
            rows=[(1, "Alice")],
            columns=["id", "name"],
        )
        select_description = [(col, None, None, None, None, None, None) for col in ("id", "name")]

        def _advance_to_select() -> bool:
            mock_cursor.description = select_description
            return True

        mock_cursor.description = None
        mock_cursor.nextset.side_effect = _advance_to_select
        connector._connection = mock_conn
        connector._cursor = mock_cursor

        rows = await connector.execute(
            "DECLARE @x int = 1;\nSELECT id, name FROM users",
            1,
        )

        mock_cursor.nextset.assert_called_once()
        assert rows == [{"id": 1, "name": "Alice"}]

    async def test_execute_returns_empty_for_non_select(self):
        config = _make_config()
        connector = SqlServerConnector(config)
        mock_conn, mock_cursor = _make_mock_connection(rows=[], columns=[])
        mock_cursor.description = None  # DML statements have no description
        mock_cursor.nextset.return_value = False
        connector._connection = mock_conn
        connector._cursor = mock_cursor

        rows = await connector.execute("DELETE FROM users WHERE id = ?", {"id": 1})
        assert rows == []

    async def test_execute_without_connect_raises(self):
        config = _make_config()
        connector = SqlServerConnector(config)

        with pytest.raises(RuntimeError, match="Not connected"):
            await connector.execute("SELECT 1")

    async def test_execute_many_without_connect_raises(self):
        config = _make_config()
        connector = SqlServerConnector(config)

        with pytest.raises(RuntimeError, match="Not connected"):
            await connector.execute_many("INSERT INTO t VALUES (?)", [{"v": 1}])

    async def test_disconnect_closes_cursor_and_connection(self):
        config = _make_config()
        connector = SqlServerConnector(config)
        mock_conn, mock_cursor = _make_mock_connection()
        connector._connection = mock_conn
        connector._cursor = mock_cursor

        await connector.disconnect()

        mock_cursor.close.assert_called_once()
        mock_conn.close.assert_called_once()


# ---------------------------------------------------------------------------
# Regression: pyodbc parameter-marker handling
#
# pyodbc treats ``cursor.execute(sql, None)`` as supplying a single NULL
# parameter. For a marker-less query (e.g. the dependency/schema discovery
# queries) this raises:
#   "The SQL contains 0 parameter markers, but 1 parameters were supplied"
# which previously surfaced as a 502 on POST /api/v1/discover. The connector
# must therefore call execute() WITHOUT a second positional argument when no
# parameters are supplied.
# ---------------------------------------------------------------------------

class _PyodbcSemanticsCursor(MagicMock):
    """A cursor mock that faithfully reproduces pyodbc's marker/param check."""

    def nextset(self) -> bool:
        return False

    def execute(self, sql, *parameters):  # noqa: D401 - mimics pyodbc signature
        markers = sql.count("?")
        if not parameters:
            supplied = 0
        else:
            # pyodbc unpacks a single sequence argument; anything else
            # (including a bare None) counts as that many scalar parameters.
            first = parameters[0]
            if len(parameters) == 1 and isinstance(first, (list, tuple)):
                supplied = len(first)
            else:
                supplied = len(parameters)
        if markers != supplied:
            raise Exception(
                f"('The SQL contains {markers} parameter markers, but {supplied} "
                f"parameters were supplied', 'HY000')"
            )
        return self

    def fetchall(self):
        return []


class TestParameterMarkerHandling:
    async def test_paramless_query_does_not_pass_none_to_pyodbc(self):
        """A query with no params must be executed without a second arg."""
        config = _make_config()
        connector = SqlServerConnector(config)
        mock_conn, mock_cursor = _make_mock_connection(rows=[], columns=[])
        connector._connection = mock_conn
        connector._cursor = mock_cursor

        await connector.execute("SELECT 1 FROM sys.objects")

        # Must be called with the query alone — never (query, None).
        mock_cursor.execute.assert_called_once_with("SELECT 1 FROM sys.objects")

    async def test_paramless_marker_less_query_succeeds(self):
        """Reproduces the discovery 502: a 0-marker query must not error."""
        config = _make_config()
        connector = SqlServerConnector(config)
        cursor = _PyodbcSemanticsCursor()
        cursor.description = None
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = cursor
        connector._connection = mock_conn
        connector._cursor = cursor

        # No params, no markers — would raise under the old `, None` behaviour.
        rows = await connector.execute(
            "SELECT * FROM sys.sql_expression_dependencies"
        )
        assert rows == []

    async def test_params_are_passed_as_sequence(self):
        """Parameterised queries still bind values positionally."""
        config = _make_config()
        connector = SqlServerConnector(config)
        cursor = _PyodbcSemanticsCursor()
        cursor.description = None
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = cursor
        connector._connection = mock_conn
        connector._cursor = cursor

        rows = await connector.execute(
            "SELECT name FROM sys.tables WHERE schema_name = ?", {"schema": "dbo"}
        )
        assert rows == []


# ---------------------------------------------------------------------------
# Connection config
# ---------------------------------------------------------------------------

class TestSqlServerConnectionConfig:
    def test_connection_string_contains_driver_and_host(self):
        config = _make_config()
        cs = config.connection_string
        assert "DRIVER=" in cs
        assert "SERVER=localhost,1433" in cs
        assert "DATABASE=testdb" in cs
        assert "UID=sa" in cs

    def test_dsn_does_not_contain_password(self):
        config = _make_config(password="super_secret")
        assert "super_secret" not in config.dsn
        assert "UID=sa" in config.dsn

    def test_sqlserver_config_from_entry_honors_ssl_enabled(self):
        from infrastructure.sqlserver.sqlserver_connector import sqlserver_config_from_entry

        config = sqlserver_config_from_entry(
            {
                "host": "localhost",
                "port": 1433,
                "database": "db",
                "username": "sa",
                "ssl_enabled": True,
            },
            password="pw",
        )
        assert config.trust_server_certificate is True
        assert "TrustServerCertificate=yes" in config.connection_string

    def test_sqlserver_config_from_resolved_honors_trust_flag(self):
        from infrastructure.sqlserver.sqlserver_connector import sqlserver_config_from_resolved

        config = sqlserver_config_from_resolved(
            {
                "host": "localhost",
                "port": 1433,
                "database": "db",
                "username": "sa",
                "trust_server_certificate": True,
            },
            password="pw",
            schema="Sales",
        )
        assert config.trust_server_certificate is True
        assert config.schema == "Sales"
        assert "TrustServerCertificate=yes" in config.connection_string
