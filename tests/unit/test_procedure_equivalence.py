"""Unit tests for procedure equivalence harness (§11.2)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from domains.validation.procedure_equivalence_harness import (
    EquivalenceCase,
    ProcedureEquivalenceHarness,
    compare_resultsets,
    load_corpus,
)


def test_compare_resultsets_equal():
    src = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
    tgt = [{"a": 2, "b": "y"}, {"a": 1, "b": "x"}]
    ok, detail = compare_resultsets(src, tgt)
    assert ok is True
    assert detail == ""


def test_compare_resultsets_row_count_mismatch():
    ok, detail = compare_resultsets([{"a": 1}], [])
    assert ok is False
    assert "row count" in detail


def test_load_corpus():
    corpus_path = Path(__file__).parents[1] / "fixtures" / "procedure_equivalence_corpus.json"
    cases = load_corpus(corpus_path)
    assert len(cases) >= 4
    assert cases[0].name == "simple_scalar_add"


@pytest.mark.asyncio
async def test_harness_convertibility_mode():
    harness = ProcedureEquivalenceHarness()
    case = EquivalenceCase(
        name="inline_test",
        source_sql="CREATE PROCEDURE dbo.p AS BEGIN SELECT 1 AS n; END",
        skip_runtime=True,
    )
    result = await harness.run_case(case)
    assert result.conversion_success is True
    assert result.passed is True
    assert result.converted_sql


@pytest.mark.asyncio
async def test_harness_runtime_equivalence_with_mocks():
    source = AsyncMock()
    target = AsyncMock()
    rows = [{"result": 5}]
    source.execute = AsyncMock(return_value=rows)
    target.execute = AsyncMock(return_value=rows)

    harness = ProcedureEquivalenceHarness(source_connector=source, target_connector=target)
    case = EquivalenceCase(
        name="runtime_mock",
        source_sql="CREATE PROCEDURE dbo.p AS BEGIN SELECT 1 AS n; END",
        source_call="EXEC dbo.p",
        target_call="SELECT * FROM dbo.p()",
        skip_runtime=False,
    )
    result = await harness.run_case(case)
    assert result.passed is True
    assert result.source_row_count == 1
    assert result.target_row_count == 1


@pytest.mark.asyncio
async def test_corpus_convertibility_batch():
    corpus_path = Path(__file__).parents[1] / "fixtures" / "procedure_equivalence_corpus.json"
    cases = load_corpus(corpus_path)
    harness = ProcedureEquivalenceHarness()
    results = await harness.run_corpus(cases)
    summary = harness.summary(results)
    assert summary["total"] == len(cases)
    assert summary["passed"] >= 3
    assert summary["semantic_equivalence_pct"] > 0
