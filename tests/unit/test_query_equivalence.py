"""Unit tests for inline query equivalence harness."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from domains.validation.query_equivalence_harness import (
    QueryEquivalenceCase,
    QueryEquivalenceHarness,
    convert_tsql_query,
)


def test_convert_tsql_query_datediff():
    sql = convert_tsql_query(
        "SELECT DATEDIFF(SECOND, '2026-01-01', '2026-01-01 00:02:00') AS secs"
    )
    assert "EXTRACT" in sql.upper() or "EPOCH" in sql.upper()


@pytest.mark.asyncio
async def test_query_harness_mock():
    source = AsyncMock()
    target = AsyncMock()
    rows = [{"secs": 120}]
    source.execute = AsyncMock(return_value=rows)
    target.execute = AsyncMock(return_value=rows)

    harness = QueryEquivalenceHarness(source, target)
    case = QueryEquivalenceCase(
        name="datediff",
        source_sql="SELECT DATEDIFF(SECOND, '2026-01-01', '2026-01-01 00:02:00') AS secs",
    )
    result = await harness.run_case(case)
    assert result.passed is True


def test_query_corpus_loads():
    path = Path(__file__).parents[1] / "fixtures" / "query_equivalence_corpus.json"
    data = json.loads(path.read_text())
    assert len(data["cases"]) >= 4
