"""
Module: tests/unit/test_l3_l4_validators.py
Purpose: Unit tests for L3ChunkHashValidator and L4StatisticalSamplingValidator.
         Uses AsyncMock connectors — no real database required.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from domains.validation.l3_l4_validators import (
    L3ChunkHashValidator,
    L4StatisticalSamplingValidator,
    _compare_rows,
)
from domains.validation.validation_engine import ValidationStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_connector(execute_return: list) -> MagicMock:
    conn = MagicMock()
    conn.execute = AsyncMock(return_value=execute_return)
    return conn


# ---------------------------------------------------------------------------
# _compare_rows helper
# ---------------------------------------------------------------------------


class TestCompareRows:
    def test_identical_rows_return_empty(self):
        src = {"id": 1, "name": "Alice", "score": 9.5}
        tgt = {"id": 1, "name": "Alice", "score": 9.5}
        assert _compare_rows(src, tgt) == []

    def test_different_value_detected(self):
        src = {"id": 1, "name": "Alice"}
        tgt = {"id": 1, "name": "Bob"}
        diffs = _compare_rows(src, tgt)
        assert "name" in diffs

    def test_null_equality_treated_as_equal(self):
        src = {"id": 1, "val": None}
        tgt = {"id": 1, "val": None}
        assert _compare_rows(src, tgt) == []

    def test_null_vs_value_is_diff(self):
        src = {"id": 1, "val": None}
        tgt = {"id": 1, "val": "x"}
        diffs = _compare_rows(src, tgt)
        assert "val" in diffs

    def test_numeric_type_coercion_int_float(self):
        # int 5 vs float 5.0 should not be a mismatch
        src = {"amount": 5}
        tgt = {"amount": 5.0}
        assert _compare_rows(src, tgt) == []

    def test_case_insensitive_column_names(self):
        src = {"ID": 1, "Name": "Alice"}
        tgt = {"id": 1, "name": "Alice"}
        assert _compare_rows(src, tgt) == []


# ---------------------------------------------------------------------------
# L3ChunkHashValidator
# ---------------------------------------------------------------------------


class TestL3ChunkHashValidator:
    @pytest.mark.asyncio
    async def test_matching_chunk_passes(self):
        validator = L3ChunkHashValidator()
        src_conn = _mock_connector([{"cnt": 100, "min_pk": 1, "max_pk": 100}])
        tgt_conn = _mock_connector([{"cnt": 100, "min_pk": 1, "max_pk": 100}])
        result = await validator.validate_chunk(
            src_conn, tgt_conn, "orders", ["id"], 1, 100, schema="dbo"
        )
        assert result.status == ValidationStatus.PASSED
        assert result.source_count == 100
        assert result.target_count == 100

    @pytest.mark.asyncio
    async def test_count_mismatch_fails(self):
        validator = L3ChunkHashValidator()
        src_conn = _mock_connector([{"cnt": 100, "min_pk": 1, "max_pk": 100}])
        tgt_conn = _mock_connector([{"cnt": 95, "min_pk": 1, "max_pk": 100}])
        result = await validator.validate_chunk(
            src_conn, tgt_conn, "orders", ["id"], 1, 100, schema="dbo"
        )
        assert result.status == ValidationStatus.FAILED
        assert result.issues
        assert "count" in result.issues[0].message

    @pytest.mark.asyncio
    async def test_max_pk_mismatch_fails(self):
        validator = L3ChunkHashValidator()
        src_conn = _mock_connector([{"cnt": 100, "min_pk": 1, "max_pk": 100}])
        tgt_conn = _mock_connector([{"cnt": 100, "min_pk": 1, "max_pk": 99}])
        result = await validator.validate_chunk(
            src_conn, tgt_conn, "orders", ["id"], 1, 100, schema="dbo"
        )
        assert result.status == ValidationStatus.FAILED

    @pytest.mark.asyncio
    async def test_numeric_sum_mismatch_fails(self):
        validator = L3ChunkHashValidator()
        src_conn = _mock_connector([{"cnt": 10, "min_pk": 1, "max_pk": 10, "sum_amount": 500.0}])
        tgt_conn = _mock_connector([{"cnt": 10, "min_pk": 1, "max_pk": 10, "sum_amount": 450.0}])
        result = await validator.validate_chunk(
            src_conn, tgt_conn, "orders", ["id"], 1, 10,
            schema="dbo", numeric_columns=["amount"]
        )
        assert result.status == ValidationStatus.FAILED

    @pytest.mark.asyncio
    async def test_numeric_sum_match_passes(self):
        validator = L3ChunkHashValidator()
        src_conn = _mock_connector([{"cnt": 10, "min_pk": 1, "max_pk": 10, "sum_amount": 500.0}])
        tgt_conn = _mock_connector([{"cnt": 10, "min_pk": 1, "max_pk": 10, "sum_amount": 500.0}])
        result = await validator.validate_chunk(
            src_conn, tgt_conn, "orders", ["id"], 1, 10,
            schema="dbo", numeric_columns=["amount"]
        )
        assert result.status == ValidationStatus.PASSED

    @pytest.mark.asyncio
    async def test_full_table_range_without_bounds_passes(self):
        validator = L3ChunkHashValidator()
        src_conn = _mock_connector([{"cnt": 10, "min_pk": 1, "max_pk": 10}])
        tgt_conn = _mock_connector([{"cnt": 10, "min_pk": 1, "max_pk": 10}])
        result = await validator.validate_chunk(
            src_conn, tgt_conn, "orders", ["id"], None, None, schema="dbo"
        )
        assert result.status == ValidationStatus.PASSED
        src_sql = src_conn.execute.await_args.args[0]
        assert "WHERE" not in src_sql

    @pytest.mark.asyncio
    async def test_query_failure_returns_error(self):
        validator = L3ChunkHashValidator()
        src_conn = MagicMock()
        src_conn.execute = AsyncMock(side_effect=Exception("connection lost"))
        tgt_conn = _mock_connector([{"cnt": 10, "min_pk": 1, "max_pk": 10}])
        result = await validator.validate_chunk(
            src_conn, tgt_conn, "orders", ["id"], 1, 10, schema="dbo"
        )
        assert result.status == ValidationStatus.ERROR

    @pytest.mark.asyncio
    async def test_validate_all_chunks_aggregates_results(self):
        validator = L3ChunkHashValidator()
        src_conn = _mock_connector([{"cnt": 10, "min_pk": 1, "max_pk": 10}])
        tgt_conn = _mock_connector([{"cnt": 10, "min_pk": 1, "max_pk": 10}])
        chunks = [(1, 10), (11, 20), (21, 30)]
        results = await validator.validate_all_chunks(
            src_conn, tgt_conn, "orders", ["id"], chunks, schema="dbo"
        )
        assert len(results) == 3
        assert all(r.status == ValidationStatus.PASSED for r in results)

    @pytest.mark.asyncio
    async def test_composite_pk_full_table_uses_count_only(self):
        validator = L3ChunkHashValidator()
        src_conn = _mock_connector([{"cnt": 42}])
        tgt_conn = _mock_connector([{"cnt": 42}])
        result = await validator.validate_chunk(
            src_conn,
            tgt_conn,
            "EmployeePayHistory",
            ["BusinessEntityID", "RateChangeDate", "Rate"],
            None,
            None,
            schema="HumanResources",
            target_schema="public",
        )
        assert result.status == ValidationStatus.PASSED
        src_sql = src_conn.execute.await_args.args[0]
        assert "MIN" not in src_sql
        tgt_sql = tgt_conn.execute.await_args.args[0]
        assert '"public".' in tgt_sql

    @pytest.mark.asyncio
    async def test_target_query_uses_positional_params(self):
        validator = L3ChunkHashValidator()
        src_conn = _mock_connector([{"cnt": 5, "min_pk": 1, "max_pk": 5}])
        tgt_conn = _mock_connector([{"cnt": 5, "min_pk": 1, "max_pk": 5}])
        await validator.validate_chunk(
            src_conn,
            tgt_conn,
            "orders",
            ["id"],
            1,
            5,
            schema="dbo",
            target_schema="app",
        )
        tgt_call = tgt_conn.execute.await_args
        assert tgt_call.args[1:] == (1, 5)


# ---------------------------------------------------------------------------
# L4StatisticalSamplingValidator
# ---------------------------------------------------------------------------


class TestL4StatisticalSamplingValidator:
    def test_invalid_sample_pct_raises(self):
        with pytest.raises(ValueError):
            L4StatisticalSamplingValidator(sample_pct=0.0)
        with pytest.raises(ValueError):
            L4StatisticalSamplingValidator(sample_pct=101.0)

    @pytest.mark.asyncio
    async def test_all_matching_rows_passes(self):
        # row_count provided → _count_source is NOT called;
        # first execute call goes to _sample_source_pks
        validator = L4StatisticalSamplingValidator(sample_pct=100.0, min_sample=1)
        src_conn = MagicMock()
        src_conn.execute = AsyncMock(side_effect=[
            [{"id": 1}, {"id": 2}],    # _sample_source_pks
            [{"id": 1, "name": "A"}],  # fetch row 1 from source
            [{"id": 2, "name": "B"}],  # fetch row 2 from source
        ])
        tgt_conn = MagicMock()
        tgt_conn.execute = AsyncMock(side_effect=[
            [{"id": 1, "name": "A"}],  # fetch row 1 from target
            [{"id": 2, "name": "B"}],  # fetch row 2 from target
        ])
        result = await validator.validate(
            src_conn, tgt_conn, "users", ["id"], schema="dbo", row_count=3
        )
        assert result.status == ValidationStatus.PASSED

    @pytest.mark.asyncio
    async def test_mismatched_row_fails(self):
        # row_count=1 provided → first call is _sample_source_pks
        validator = L4StatisticalSamplingValidator(sample_pct=100.0, min_sample=1)
        src_conn = MagicMock()
        src_conn.execute = AsyncMock(side_effect=[
            [{"id": 1}],               # _sample_source_pks
            [{"id": 1, "name": "Alice"}],  # fetch row from source
        ])
        tgt_conn = MagicMock()
        tgt_conn.execute = AsyncMock(return_value=[{"id": 1, "name": "Bob"}])
        result = await validator.validate(
            src_conn, tgt_conn, "users", ["id"], schema="dbo", row_count=1
        )
        assert result.status == ValidationStatus.FAILED
        assert result.issues

    @pytest.mark.asyncio
    async def test_missing_target_row_fails(self):
        # row_count=1 provided → first call is _sample_source_pks
        validator = L4StatisticalSamplingValidator(min_sample=1)
        src_conn = MagicMock()
        src_conn.execute = AsyncMock(side_effect=[
            [{"id": 42}],              # _sample_source_pks
            [{"id": 42, "val": "x"}],  # fetch row from source
        ])
        tgt_conn = MagicMock()
        tgt_conn.execute = AsyncMock(return_value=[])  # row missing in target
        result = await validator.validate(
            src_conn, tgt_conn, "items", ["id"], schema="dbo", row_count=1
        )
        assert result.status == ValidationStatus.FAILED
        assert any("missing in target" in i.message for i in result.issues)

    @pytest.mark.asyncio
    async def test_empty_source_returns_skipped(self):
        validator = L4StatisticalSamplingValidator(min_sample=1)
        src_conn = MagicMock()
        src_conn.execute = AsyncMock(side_effect=[
            [{"cnt": 0}],
            [],        # no PKs sampled
        ])
        tgt_conn = MagicMock()
        tgt_conn.execute = AsyncMock(return_value=[])
        result = await validator.validate(
            src_conn, tgt_conn, "empty_table", ["id"], schema="dbo", row_count=0
        )
        assert result.status == ValidationStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_composite_pk_sampling_passes(self):
        validator = L4StatisticalSamplingValidator(sample_pct=100.0, min_sample=1)
        src_conn = MagicMock()
        src_conn.execute = AsyncMock(side_effect=[
            [{"BusinessEntityID": 1, "RateChangeDate": "2020-01-01", "Rate": 40.0}],
            [{"BusinessEntityID": 1, "RateChangeDate": "2020-01-01", "Rate": 40.0, "name": "x"}],
        ])
        tgt_conn = MagicMock()
        tgt_conn.execute = AsyncMock(return_value=[
            {"BusinessEntityID": 1, "RateChangeDate": "2020-01-01", "Rate": 40.0, "name": "x"},
        ])
        result = await validator.validate(
            src_conn,
            tgt_conn,
            "EmployeePayHistory",
            ["BusinessEntityID", "RateChangeDate", "Rate"],
            schema="HumanResources",
            target_schema="public",
            row_count=1,
        )
        assert result.status == ValidationStatus.PASSED
        tgt_call = tgt_conn.execute.await_args
        assert tgt_call.args[1:] == (1, "2020-01-01", 40.0)

    @pytest.mark.asyncio
    async def test_source_fetch_error_reports_distinct_message(self):
        validator = L4StatisticalSamplingValidator(min_sample=1)
        src_conn = MagicMock()
        src_conn.execute = AsyncMock(side_effect=[
            [{"id": 2117}],
            Exception("pyodbc cannot read hierarchyid"),
        ])
        tgt_conn = MagicMock()
        tgt_conn.execute = AsyncMock(return_value=[{"id": 2117, "name": "x"}])
        result = await validator.validate(
            src_conn, tgt_conn, "dt_MiscTypes", ["id"], schema="dbo", row_count=1
        )
        assert result.status == ValidationStatus.FAILED
        assert any(
            "could not be read from source" in i.message for i in result.issues
        )
        assert not any(
            "missing in source" in i.message for i in result.issues
        )

    @pytest.mark.asyncio
    async def test_uses_fetch_source_row_safe_when_source_database_set(self):
        validator = L4StatisticalSamplingValidator(min_sample=1)
        src_conn = MagicMock()
        src_conn.execute = AsyncMock(return_value=[{"id": 1}])
        tgt_conn = MagicMock()
        tgt_conn.execute = AsyncMock(return_value=[{"id": 1, "val": "x"}])

        with patch(
            "domains.validation.l3_l4_validators.fetch_source_row_safe",
            new_callable=AsyncMock,
        ) as mock_safe:
            from domains.migration.column_type_override import SourceRowFetchResult

            mock_safe.return_value = SourceRowFetchResult(row={"id": 1, "val": "x"})
            result = await validator.validate(
                src_conn,
                tgt_conn,
                "dt_MiscTypes",
                ["id"],
                schema="dbo",
                row_count=1,
                source_database="AppDb",
            )
        assert result.status == ValidationStatus.PASSED
        mock_safe.assert_awaited_once()
        assert src_conn.execute.await_count == 1
