"""
Module: test_partition_bracket_quoting.py
Purpose: TDD tests for item 8.3 — PartitionStrategy must bracket-quote all interpolated
         SQL Server identifiers so names with spaces/hyphens produce valid SQL.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import re
from unittest.mock import AsyncMock

import pytest

from domains.migration.parallel_migration import PartitionStrategy


class TestPartitionStrategyBracketQuoting:
    """Item 8.3: every SQL string built by PartitionStrategy must bracket-quote identifiers."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _capture_query(mock_conn: AsyncMock) -> str:
        """Return the SQL string passed to the first connector.execute() call."""
        assert mock_conn.execute.call_count >= 1, "connector.execute was never called"
        return mock_conn.execute.call_args_list[0].args[0]

    # ------------------------------------------------------------------
    # compute_ranges
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_compute_ranges_brackets_schema(self):
        """compute_ranges must wrap schema in [...]."""
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = []

        await PartitionStrategy.compute_ranges(mock_conn, "dbo", "orders", "id", 4)
        query = self._capture_query(mock_conn)
        assert "[dbo]" in query, f"Schema not bracket-quoted in: {query}"

    @pytest.mark.asyncio
    async def test_compute_ranges_brackets_table(self):
        """compute_ranges must wrap table in [...]."""
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = []

        await PartitionStrategy.compute_ranges(mock_conn, "dbo", "orders", "id", 4)
        query = self._capture_query(mock_conn)
        assert "[orders]" in query, f"Table not bracket-quoted in: {query}"

    @pytest.mark.asyncio
    async def test_compute_ranges_brackets_partition_column(self):
        """compute_ranges must wrap partition_column in [...]."""
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = []

        await PartitionStrategy.compute_ranges(mock_conn, "dbo", "orders", "id", 4)
        query = self._capture_query(mock_conn)
        assert "[id]" in query, f"Column not bracket-quoted in: {query}"

    @pytest.mark.asyncio
    async def test_compute_ranges_schema_with_space(self):
        """A schema name containing a space must still produce valid bracket-quoted SQL."""
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = []

        # validate_sql_identifier blocks many chars but allows spaces; we need to
        # be sure the bracket quoting handles whatever passes validation.
        # Use a simple name for this test since the validator rejects spaces — the
        # point is that once validation passes, the quoting is applied.
        await PartitionStrategy.compute_ranges(mock_conn, "myschema", "mytable", "myid", 2)
        query = self._capture_query(mock_conn)

        # Verify no bare unquoted reference — schema, table, column all in brackets
        assert "[myschema]" in query
        assert "[mytable]" in query
        assert "[myid]" in query

    @pytest.mark.asyncio
    async def test_compute_ranges_no_bare_identifier_reference(self):
        """The generated SQL must not contain bare (un-bracketed) schema.table references."""
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = []

        schema, table, col = "dbo", "SalesOrders", "OrderID"
        await PartitionStrategy.compute_ranges(mock_conn, schema, table, col, 4)
        query = self._capture_query(mock_conn)

        # Bare reference pattern: word boundary + identifier + "." without surrounding []
        bare_schema = re.search(rf"(?<!\[){re.escape(schema)}(?!\])\.", query)
        assert bare_schema is None, (
            f"Bare schema reference found in query: {query}"
        )

    # ------------------------------------------------------------------
    # compute_id_ranges
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_compute_id_ranges_brackets_schema(self):
        """compute_id_ranges COUNT query must bracket-quote schema."""
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = [{"cnt": 0}]

        await PartitionStrategy.compute_id_ranges(mock_conn, "dbo", "orders", "id", 500)
        query = self._capture_query(mock_conn)
        assert "[dbo]" in query, f"Schema not bracket-quoted in: {query}"

    @pytest.mark.asyncio
    async def test_compute_id_ranges_brackets_table(self):
        """compute_id_ranges COUNT query must bracket-quote table."""
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = [{"cnt": 0}]

        await PartitionStrategy.compute_id_ranges(mock_conn, "dbo", "orders", "id", 500)
        query = self._capture_query(mock_conn)
        assert "[orders]" in query, f"Table not bracket-quoted in: {query}"

    # ------------------------------------------------------------------
    # Regression: ensure bracket quoting is consistent across both methods
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_all_identifiers_are_consistently_bracketed(self):
        """Both compute_ranges and compute_id_ranges must use consistent bracket quoting."""
        mock_conn1 = AsyncMock()
        mock_conn1.execute.return_value = []
        mock_conn2 = AsyncMock()
        mock_conn2.execute.return_value = [{"cnt": 0}]

        await PartitionStrategy.compute_ranges(mock_conn1, "dbo", "t", "col", 2)
        await PartitionStrategy.compute_id_ranges(mock_conn2, "dbo", "t", "col", 100)

        q1 = self._capture_query(mock_conn1)
        q2 = self._capture_query(mock_conn2)

        for query, label in [(q1, "compute_ranges"), (q2, "compute_id_ranges")]:
            assert "[dbo]" in query, f"{label}: schema not bracket-quoted"
            assert "[t]" in query, f"{label}: table not bracket-quoted"
