"""
Module: test_postgres_params_order.py
Purpose: TDD tests for item 6.2 — PostgresConnector.execute must accept *args (positional)
         instead of dict params so asyncpg positional $1, $2, ... placeholders are always
         correctly ordered.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from infrastructure.postgres.postgres_connector import PostgresConnectionConfig, PostgresConnector


def _make_config(**overrides) -> PostgresConnectionConfig:
    defaults = {
        "host": "localhost",
        "port": 5432,
        "database": "testdb",
        "username": "pg",
        "password": "pg",
    }
    defaults.update(overrides)
    return PostgresConnectionConfig(**defaults)


class TestPostgresExecuteSignature:
    """Item 6.2: execute() must accept *args not a dict."""

    def test_execute_signature_uses_args_not_dict(self):
        """The execute() signature must NOT require a dict 'params' parameter."""
        sig = inspect.signature(PostgresConnector.execute)
        params = sig.parameters

        # Must have *args (VAR_POSITIONAL) — not a dict keyword 'params'
        has_var_positional = any(
            p.kind == inspect.Parameter.VAR_POSITIONAL
            for p in params.values()
        )
        has_dict_params = "params" in params and params["params"].annotation in (
            "dict[str, Any] | None",
            dict,
        )

        assert has_var_positional, (
            "execute() must accept *args for positional parameters, "
            "not a dict 'params' keyword argument"
        )
        assert not has_dict_params, (
            "execute() must not have a dict 'params' argument — use *args instead"
        )

    def test_execute_accepts_no_extra_args(self):
        """execute() called with just a query string (no args) must be valid."""
        sig = inspect.signature(PostgresConnector.execute)
        # Calling with (self, query) must not raise TypeError about missing params
        try:
            bound = sig.bind(MagicMock(), "SELECT 1")
            bound.apply_defaults()
        except TypeError as e:
            pytest.fail(f"execute(query) with no args raised TypeError: {e}")

    def test_execute_accepts_multiple_positional_args(self):
        """execute() must accept multiple positional values."""
        sig = inspect.signature(PostgresConnector.execute)
        try:
            bound = sig.bind(MagicMock(), "SELECT $1, $2", 10, 20)
            bound.apply_defaults()
        except TypeError as e:
            pytest.fail(f"execute(query, arg1, arg2) raised TypeError: {e}")


class TestPostgresExecutePositionalArgs:
    """Verify that positional args are forwarded correctly to asyncpg."""

    def _make_pool_and_connector(self, fetch_return=None):
        config = _make_config(ssl_mode=None)
        connector = PostgresConnector(config)

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=fetch_return or [])

        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        connector._pool = mock_pool
        return connector, mock_conn

    @pytest.mark.asyncio
    async def test_execute_no_args_calls_fetch_with_no_extra(self):
        """execute(query) — no args — must call conn.fetch(query, timeout=...)."""
        connector, mock_conn = self._make_pool_and_connector()
        await connector.execute("SELECT 1")
        mock_conn.fetch.assert_called_once()
        call_args = mock_conn.fetch.call_args
        # Only positional arg should be the query string
        assert call_args.args == ("SELECT 1",)

    @pytest.mark.asyncio
    async def test_execute_single_arg_passed_positionally(self):
        """execute(query, val) must pass val as second positional arg to conn.fetch."""
        connector, mock_conn = self._make_pool_and_connector()
        await connector.execute("SELECT $1", 42)
        call_args = mock_conn.fetch.call_args
        assert 42 in call_args.args, f"Expected 42 in positional args, got {call_args}"

    @pytest.mark.asyncio
    async def test_execute_two_args_order_preserved(self):
        """execute(query, a, b) must forward a, b in order — $1=a, $2=b."""
        connector, mock_conn = self._make_pool_and_connector()
        await connector.execute("SELECT $1, $2", "start_val", "end_val")
        call_args = mock_conn.fetch.call_args
        positional = call_args.args
        # query is first; then the args in order
        assert positional[1] == "start_val", f"$1 mismatch: {positional}"
        assert positional[2] == "end_val", f"$2 mismatch: {positional}"

    @pytest.mark.asyncio
    async def test_execute_returns_list_of_dicts(self):
        """execute() must still return list[dict] from asyncpg records."""
        fake_record = MagicMock()
        fake_record.keys.return_value = ["id", "name"]
        fake_record.values.return_value = [1, "Alice"]

        connector, mock_conn = self._make_pool_and_connector(fetch_return=[fake_record])
        result = await connector.execute("SELECT id, name FROM users WHERE id = $1", 1)
        assert result == [{"id": 1, "name": "Alice"}]


class TestPostgresExecuteManyPositional:
    """execute_many should also use positional args (tuple lists)."""

    @pytest.mark.asyncio
    async def test_execute_many_passes_tuples_not_dict_values(self):
        """execute_many must pass list-of-tuples to asyncpg, not list of dict.values()."""
        config = _make_config(ssl_mode=None)
        connector = PostgresConnector(config)

        mock_conn = AsyncMock()
        mock_conn.executemany = AsyncMock()
        mock_txn = AsyncMock()
        mock_txn.__aenter__ = AsyncMock(return_value=mock_txn)
        mock_txn.__aexit__ = AsyncMock(return_value=False)
        mock_conn.transaction = MagicMock(return_value=mock_txn)

        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        connector._pool = mock_pool

        params_list = [(1, "Alice"), (2, "Bob")]
        await connector.execute_many("INSERT INTO t VALUES ($1, $2)", params_list)

        mock_conn.executemany.assert_called_once_with(
            "INSERT INTO t VALUES ($1, $2)", [(1, "Alice"), (2, "Bob")]
        )
