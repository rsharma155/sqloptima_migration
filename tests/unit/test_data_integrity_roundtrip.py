"""Golden-dataset round-trip integrity tests (mock connectors).

Validates inclusive chunk boundaries so no rows are silently skipped —
the regression net for the §1.1 off-by-one bug.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from domains.migration.migration_engine import DataExtractor


@pytest.mark.asyncio
async def test_extract_range_inclusive_boundary_no_rows_skipped():
    """Every id from 1..25 must be extracted across three inclusive ranges."""
    all_rows = [{"id": i, "val": f"v{i}"} for i in range(1, 26)]
    extracted_ids: list[int] = []

    connector = AsyncMock()

    async def fake_execute(query, params=None):
        start = params["start"]
        end = params["end"]
        rows = [r for r in all_rows if start <= r["id"] <= end]
        extracted_ids.extend(r["id"] for r in rows)
        return rows

    connector.execute = fake_execute
    extractor = DataExtractor(connector=connector)

    ranges = [(1, 10), (11, 20), (21, 25)]
    for start, end in ranges:
        await extractor.extract_range(
            schema="dbo",
            table="users",
            column_name="id",
            start=start,
            end=end,
            columns=["id", "val"],
            order_column="id",
        )

    assert sorted(extracted_ids) == list(range(1, 26))
    assert len(extracted_ids) == 25


@pytest.mark.asyncio
async def test_extract_range_boundary_row_not_skipped():
    """The row at exactly chunk_end must be included (id=10000)."""
    connector = AsyncMock()
    connector.execute = AsyncMock(
        return_value=[{"id": 10000, "val": "boundary"}]
    )
    extractor = DataExtractor(connector=connector)
    rows = await extractor.extract_range(
        schema="dbo",
        table="big_table",
        column_name="id",
        start=9001,
        end=10000,
        columns=["id", "val"],
        order_column="id",
    )
    assert len(rows) == 1
    assert rows[0]["id"] == 10000
    query = connector.execute.call_args[0][0]
    assert "<= ?" in query or "<=?" in query.replace(" ", "")
