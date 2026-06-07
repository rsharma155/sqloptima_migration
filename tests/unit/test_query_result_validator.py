"""Tests for query result validation and streaming comparison.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from unittest.mock import AsyncMock

import pytest

from domains.validation.query_result_validator import (
    QueryPair,
    QueryResultValidator,
    RowDiff,
    StreamingComparator,
    StreamingComparisonConfig,
    StreamingComparisonResult,
)
from domains.validation.validation_engine import ValidationStatus


class TestQueryPair:
    def test_create(self):
        qp = QueryPair(
            name="test",
            source_query="SELECT * FROM dbo.users",
            target_query="SELECT * FROM users",
        )
        assert qp.name == "test"


class TestStreamingComparisonConfig:
    def test_defaults(self):
        c = StreamingComparisonConfig()
        assert c.chunk_size == 1000
        assert c.abort_on_first_mismatch is True


class TestRowDiff:
    def test_create(self):
        rd = RowDiff(
            row_number=1,
            key_values={"id": 42},
            differences={"name": ("Alice", "Bob")},
        )
        assert rd.row_number == 1
        assert rd.key_values["id"] == 42
        assert rd.differences["name"] == ("Alice", "Bob")


class TestStreamingComparisonResult:
    def test_create(self):
        r = StreamingComparisonResult()
        assert r.success is True
        assert r.total_rows_compared == 0


class TestQueryResultValidator:
    @pytest.fixture
    def validator(self):
        return QueryResultValidator()

    @pytest.mark.asyncio
    async def test_matching_queries(self, validator):
        mock_source = AsyncMock()
        mock_source.execute.return_value = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
        ]
        mock_target = AsyncMock()
        mock_target.execute.return_value = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
        ]

        qp = QueryPair(name="users", source_query="SELECT * FROM users", target_query="SELECT * FROM users")
        result = await validator.validate(mock_source, mock_target, qp)
        assert result.status == ValidationStatus.PASSED

    @pytest.mark.asyncio
    async def test_row_count_mismatch(self, validator):
        mock_source = AsyncMock()
        mock_source.execute.return_value = [{"id": 1}, {"id": 2}]
        mock_target = AsyncMock()
        mock_target.execute.return_value = [{"id": 1}]

        qp = QueryPair(name="users", source_query="SELECT * FROM users", target_query="SELECT * FROM users")
        result = await validator.validate(mock_source, mock_target, qp)
        assert result.status == ValidationStatus.FAILED

    @pytest.mark.asyncio
    async def test_column_mismatch(self, validator):
        mock_source = AsyncMock()
        mock_source.execute.return_value = [{"id": 1, "name": "Alice"}]
        mock_target = AsyncMock()
        mock_target.execute.return_value = [{"id": 1, "full_name": "Alice"}]

        qp = QueryPair(name="users", source_query="SELECT * FROM users", target_query="SELECT * FROM users")
        result = await validator.validate(mock_source, mock_target, qp)
        assert result.status == ValidationStatus.FAILED

    @pytest.mark.asyncio
    async def test_data_mismatch(self, validator):
        mock_source = AsyncMock()
        mock_source.execute.return_value = [{"id": 1, "name": "Alice"}]
        mock_target = AsyncMock()
        mock_target.execute.return_value = [{"id": 1, "name": "Bob"}]

        qp = QueryPair(name="users", source_query="SELECT * FROM users", target_query="SELECT * FROM users")
        result = await validator.validate(mock_source, mock_target, qp)
        assert result.status == ValidationStatus.FAILED
        assert len(result.issues) == 1

    @pytest.mark.asyncio
    async def test_empty_both(self, validator):
        mock_source = AsyncMock()
        mock_source.execute.return_value = []
        mock_target = AsyncMock()
        mock_target.execute.return_value = []

        qp = QueryPair(name="empty", source_query="SELECT * FROM empty", target_query="SELECT * FROM empty")
        result = await validator.validate(mock_source, mock_target, qp)
        assert result.status == ValidationStatus.PASSED

    @pytest.mark.asyncio
    async def test_query_error(self, validator):
        mock_source = AsyncMock()
        mock_source.execute.side_effect = Exception("Syntax error")
        mock_target = AsyncMock()

        qp = QueryPair(name="failing", source_query="INVALID SQL", target_query="INVALID SQL")
        result = await validator.validate(mock_source, mock_target, qp)
        assert result.status == ValidationStatus.ERROR

    @pytest.mark.asyncio
    async def test_reports_first_10_issues(self, validator):
        mock_source = AsyncMock()
        mock_source.execute.return_value = [{"id": i, "val": "x"} for i in range(20)]
        mock_target = AsyncMock()
        mock_target.execute.return_value = [{"id": i, "val": "y"} for i in range(20)]

        qp = QueryPair(name="many", source_query="SELECT * FROM many", target_query="SELECT * FROM many")
        result = await validator.validate(mock_source, mock_target, qp)
        assert result.status == ValidationStatus.FAILED
        assert len(result.issues) == 10


class TestStreamingComparator:
    @pytest.fixture
    def comparator(self):
        return StreamingComparator(StreamingComparisonConfig(chunk_size=5, abort_on_first_mismatch=True))

    @pytest.mark.asyncio
    async def test_matching_tables(self, comparator):
        call_count_s = [0]
        call_count_t = [0]

        async def source_execute(*args, **kwargs):
            call_count_s[0] += 1
            if call_count_s[0] == 1:
                return [{"id": i, "name": f"User{i}"} for i in range(5)]
            return []

        async def target_execute(*args, **kwargs):
            call_count_t[0] += 1
            if call_count_t[0] == 1:
                return [{"id": i, "name": f"User{i}"} for i in range(5)]
            return []

        mock_source = AsyncMock()
        mock_source.execute.side_effect = source_execute
        mock_target = AsyncMock()
        mock_target.execute.side_effect = target_execute

        result = await comparator.compare_tables(
            mock_source, mock_target, "dbo", "users", ["id", "name"], "id"
        )
        assert result.success is True
        assert result.diffs == []

    @pytest.mark.asyncio
    async def test_mismatch_detected(self, comparator):
        call_count_s = [0]
        call_count_t = [0]

        async def source_execute(*args, **kwargs):
            call_count_s[0] += 1
            if call_count_s[0] == 1:
                return [{"id": 1, "name": "Alice"}]
            return []

        async def target_execute(*args, **kwargs):
            call_count_t[0] += 1
            if call_count_t[0] == 1:
                return [{"id": 1, "name": "Bob"}]
            return []

        mock_source = AsyncMock()
        mock_source.execute.side_effect = source_execute
        mock_target = AsyncMock()
        mock_target.execute.side_effect = target_execute

        result = await comparator.compare_tables(
            mock_source, mock_target, "dbo", "users", ["id", "name"], "id"
        )
        assert result.success is False
        assert len(result.diffs) > 0

    @pytest.mark.asyncio
    async def test_empty_tables(self, comparator):
        mock_source = AsyncMock()
        mock_source.execute.return_value = []
        mock_target = AsyncMock()
        mock_target.execute.return_value = []

        result = await comparator.compare_tables(
            mock_source, mock_target, "dbo", "empty", ["id"], "id"
        )
        assert result.success is True
        assert result.total_rows_compared == 0

    @pytest.mark.asyncio
    async def test_handles_error(self, comparator):
        mock_source = AsyncMock()
        mock_source.execute.side_effect = Exception("DB error")
        mock_target = AsyncMock()

        result = await comparator.compare_tables(
            mock_source, mock_target, "dbo", "failing", ["id"], "id"
        )
        assert result.success is False
