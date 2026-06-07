"""
Module: tests/unit/test_validation_dba_fixes.py
Purpose: TDD tests for DBA feedback fixes in validation_engine.py:
         4.1 — AggregateValidator must append ValidationIssue, not CompatibilityIssue.
         4.2 — SchemaValidator must not flag NVARCHAR→VARCHAR as a type mismatch.
         4.3 — RowCountValidator._count_target must accept a schema parameter.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from domains.validation.validation_engine import (
    AggregateValidator,
    RowCountValidator,
    SchemaValidator,
    ValidationIssue,
    ValidationStatus,
)


class TestAggregateValidatorUsesCorrectIssueType:
    """
    Issue 4.1: AggregateValidator must append ValidationIssue objects to
    ValidationResult.issues, never CompatibilityIssue.
    """

    @pytest.mark.asyncio
    async def test_failed_aggregate_query_appends_validation_issue(self):
        """When the aggregate query fails (returns None), the issue type must be ValidationIssue."""
        validator = AggregateValidator()
        src = AsyncMock()
        src.execute = AsyncMock(return_value=[])  # simulates empty / failed query
        tgt = AsyncMock()
        tgt.execute = AsyncMock(return_value=[])

        result = await validator.validate(
            source_connector=src,
            target_connector=tgt,
            table_name="orders",
            schema="dbo",
            aggregate_columns=["id"],
        )
        for issue in result.issues:
            assert isinstance(issue, ValidationIssue), (
                f"Expected ValidationIssue, got {type(issue).__name__} — fix 4.1 not applied"
            )


class TestSchemaValidatorTypeEquivalence:
    """
    Issue 4.2: Known-equivalent cross-database types (NVARCHAR→VARCHAR, etc.)
    must NOT be reported as type mismatches.
    """

    @pytest.mark.asyncio
    async def test_nvarchar_to_varchar_is_not_a_mismatch(self):
        validator = SchemaValidator()
        source_cols = [{"column_name": "name", "data_type": "NVARCHAR"}]
        target_cols = [{"column_name": "name", "data_type": "VARCHAR"}]
        result = await validator.validate_columns(source_cols, target_cols, "users")
        type_mismatch_issues = [
            i for i in result.issues if "type mismatch" in i.message.lower()
            and "name" in i.message
        ]
        assert not type_mismatch_issues, (
            "NVARCHAR→VARCHAR must not be a type mismatch — it is the expected migration mapping"
        )

    @pytest.mark.asyncio
    async def test_nchar_to_char_is_not_a_mismatch(self):
        validator = SchemaValidator()
        src = [{"column_name": "code", "data_type": "NCHAR"}]
        tgt = [{"column_name": "code", "data_type": "CHAR"}]
        result = await validator.validate_columns(src, tgt, "t")
        issues = [i for i in result.issues if "type mismatch" in i.message.lower()]
        assert not issues

    @pytest.mark.asyncio
    async def test_datetime_to_timestamp_is_not_a_mismatch(self):
        validator = SchemaValidator()
        src = [{"column_name": "created_at", "data_type": "DATETIME"}]
        tgt = [{"column_name": "created_at", "data_type": "TIMESTAMP"}]
        result = await validator.validate_columns(src, tgt, "t")
        issues = [i for i in result.issues if "type mismatch" in i.message.lower()]
        assert not issues

    @pytest.mark.asyncio
    async def test_uniqueidentifier_to_uuid_is_not_a_mismatch(self):
        validator = SchemaValidator()
        src = [{"column_name": "uid", "data_type": "UNIQUEIDENTIFIER"}]
        tgt = [{"column_name": "uid", "data_type": "UUID"}]
        result = await validator.validate_columns(src, tgt, "t")
        issues = [i for i in result.issues if "type mismatch" in i.message.lower()]
        assert not issues

    @pytest.mark.asyncio
    async def test_int_to_integer_is_not_a_mismatch(self):
        validator = SchemaValidator()
        src = [{"column_name": "qty", "data_type": "INT"}]
        tgt = [{"column_name": "qty", "data_type": "INTEGER"}]
        result = await validator.validate_columns(src, tgt, "t")
        issues = [i for i in result.issues if "type mismatch" in i.message.lower()]
        assert not issues

    @pytest.mark.asyncio
    async def test_genuine_type_mismatch_still_reported(self):
        """A real type mismatch (VARCHAR→JSONB) must still be flagged."""
        validator = SchemaValidator()
        src = [{"column_name": "data", "data_type": "VARCHAR"}]
        tgt = [{"column_name": "data", "data_type": "JSONB"}]
        result = await validator.validate_columns(src, tgt, "t")
        issues = [i for i in result.issues if "type mismatch" in i.message.lower()]
        assert issues, "Genuine type mismatches (VARCHAR→JSONB) must still be reported"


class TestRowCountTargetSchemaQualification:
    """
    Issue 4.3: _count_target must accept a schema parameter and qualify the
    table name so non-public schemas are correctly counted.
    """

    @pytest.mark.asyncio
    async def test_count_target_accepts_schema_kwarg(self):
        """_count_target must accept a schema argument (not just table)."""
        import inspect
        sig = inspect.signature(RowCountValidator._count_target)
        assert "schema" in sig.parameters, (
            "_count_target must have a 'schema' parameter — fix 4.3 not applied"
        )

    @pytest.mark.asyncio
    async def test_count_target_qualifies_table_with_schema(self):
        """_count_target must include the schema in the SQL query."""
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value=[{"cnt": 42}])
        count = await RowCountValidator._count_target(conn, schema="finance", table="invoices")
        assert count == 42
        # Verify the query included the schema
        call_args = conn.execute.call_args
        executed_sql = call_args[0][0]
        assert "finance" in executed_sql.lower(), (
            f"Schema 'finance' not in target count query: {executed_sql!r}"
        )
        assert "invoices" in executed_sql.lower()

    @pytest.mark.asyncio
    async def test_row_count_validator_uses_schema_for_target(self):
        """The public validate() method must pass schema to _count_target."""
        validator = RowCountValidator()
        src_conn = AsyncMock()
        src_conn.execute = AsyncMock(return_value=[{"cnt": 100}])
        tgt_conn = AsyncMock()
        tgt_conn.execute = AsyncMock(return_value=[{"cnt": 100}])

        result = await validator.validate(
            source_connector=src_conn,
            target_connector=tgt_conn,
            table_name="invoices",
            schema="finance",
        )
        assert result.status == ValidationStatus.PASSED
        # Verify target query included "finance"
        call_sql = tgt_conn.execute.call_args[0][0]
        assert "finance" in call_sql.lower(), (
            f"Target count query must include schema 'finance': {call_sql!r}"
        )
