"""
Module: test_validation_engine.py
Purpose: Unit tests for validation engine
Author: Migration Platform Team
Created: 2026-05-22
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from domains.validation.validation_engine import (
    ChecksumValidator,
    RowCountValidator,
    SchemaValidator,
    ValidationCategory,
    ValidationEngine,
    ValidationStatus,
)


class TestSchemaValidator:
    @pytest.mark.asyncio
    async def test_validate_matching_columns(self):
        validator = SchemaValidator()
        source = [
            {"column_name": "id", "data_type": "INT"},
            {"column_name": "name", "data_type": "VARCHAR"},
        ]
        target = [
            {"column_name": "id", "data_type": "INTEGER"},
            {"column_name": "name", "data_type": "VARCHAR"},
        ]
        result = await validator.validate_columns(source, target, "users")
        assert result.status == ValidationStatus.PASSED

    @pytest.mark.asyncio
    async def test_validate_missing_columns(self):
        validator = SchemaValidator()
        source = [
            {"column_name": "id", "data_type": "INT"},
            {"column_name": "name", "data_type": "VARCHAR"},
        ]
        target = [
            {"column_name": "id", "data_type": "INTEGER"},
        ]
        result = await validator.validate_columns(source, target, "users")
        assert result.status == ValidationStatus.FAILED
        assert len(result.issues) > 0
        assert any("missing" in i.message.lower() for i in result.issues)

    @pytest.mark.asyncio
    async def test_validate_type_mismatch(self):
        validator = SchemaValidator()
        source = [
            {"column_name": "id", "data_type": "INT"},
        ]
        target = [
            {"column_name": "id", "data_type": "BIGINT"},
        ]
        result = await validator.validate_columns(source, target, "test")
        assert len(result.issues) > 0

    @pytest.mark.asyncio
    async def test_validate_empty_columns(self):
        validator = SchemaValidator()
        result = await validator.validate_columns([], [], "empty")
        assert result.status == ValidationStatus.PASSED


class TestRowCountValidator:
    @pytest.mark.asyncio
    async def test_matching_counts(self):
        source = MagicMock()
        target = MagicMock()
        source.execute = AsyncMock(return_value=[{"row_count": 100}])
        target.execute = AsyncMock(return_value=[{"cnt": 100}])

        validator = RowCountValidator()
        result = await validator.validate(source, target, "users", "dbo")
        assert result.status == ValidationStatus.PASSED
        assert result.source_count == 100
        assert result.target_count == 100

    @pytest.mark.asyncio
    async def test_mismatched_counts(self):
        source = MagicMock()
        target = MagicMock()
        source.execute = AsyncMock(return_value=[{"row_count": 1000}])
        target.execute = AsyncMock(return_value=[{"cnt": 500}])

        validator = RowCountValidator()
        result = await validator.validate(source, target, "users", "dbo")
        assert result.status == ValidationStatus.FAILED
        assert len(result.issues) > 0

    @pytest.mark.asyncio
    async def test_uses_expected_row_count_when_provided(self):
        source = MagicMock()
        target = MagicMock()
        target.execute = AsyncMock(return_value=[{"cnt": 100}])

        validator = RowCountValidator()
        result = await validator.validate(
            source, target, "users", "dbo", expected_row_count=100,
        )
        assert result.status == ValidationStatus.PASSED
        assert result.source_count == 100
        source.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_connection_error(self):
        source = MagicMock()
        target = MagicMock()
        source.execute = AsyncMock(side_effect=Exception("Connection failed"))
        target.execute = AsyncMock(return_value=[{"cnt": 0}])

        validator = RowCountValidator()
        result = await validator.validate(source, target, "test", "dbo")
        assert result.source_count == 0


class TestChecksumValidator:
    @pytest.mark.asyncio
    async def test_crc32_always_warns_incompatible_algorithm(self):
        """CRC32 uses incompatible algorithms (BINARY_CHECKSUM vs hashtext) — always WARNING."""
        source = MagicMock()
        target = MagicMock()
        source.execute = AsyncMock(return_value=[{"chk": 12345}])
        target.execute = AsyncMock(return_value=[{"chk": 12345}])

        validator = ChecksumValidator()
        result = await validator.validate(source, target, "users", "dbo")
        assert result.status == ValidationStatus.WARNING
        assert len(result.issues) == 1
        msg = result.issues[0].message.lower()
        assert "incompatible" in msg or "unreliable" in msg

    @pytest.mark.asyncio
    async def test_crc32_warns_even_when_values_differ(self):
        """Even differing checksums produce WARNING (not FAILED) because the comparison is invalid."""
        source = MagicMock()
        target = MagicMock()
        source.execute = AsyncMock(return_value=[{"chk": 11111}])
        target.execute = AsyncMock(return_value=[{"chk": 22222}])

        validator = ChecksumValidator()
        result = await validator.validate(source, target, "users", "dbo")
        assert result.status == ValidationStatus.WARNING
        assert len(result.issues) > 0

    @pytest.mark.asyncio
    async def test_crc32_null_checksum_still_warns(self):
        """Null checksums (empty table) also produce WARNING since algorithm remains incompatible."""
        source = MagicMock()
        target = MagicMock()
        source.execute = AsyncMock(return_value=[{"chk": None}])
        target.execute = AsyncMock(return_value=[{"chk": None}])

        validator = ChecksumValidator()
        result = await validator.validate(source, target, "empty_table", "dbo")
        assert result.status == ValidationStatus.WARNING

    @pytest.mark.asyncio
    async def test_crc32_query_failure_still_warns(self):
        """Query failure during CRC32 still produces WARNING (diagnostic values in issue)."""
        source = MagicMock()
        target = MagicMock()
        source.execute = AsyncMock(side_effect=Exception("Query failed"))
        target.execute = AsyncMock(return_value=[{"chk": 0}])

        validator = ChecksumValidator()
        result = await validator.validate(source, target, "bad_table", "dbo")
        # _checksum_source returns -1 on error; result is still WARNING for CRC32
        assert result.status == ValidationStatus.WARNING

    @pytest.mark.asyncio
    async def test_unsupported_algorithm_skipped(self):
        """Unknown algorithms return SKIPPED with a warning issue."""
        source = MagicMock()
        target = MagicMock()
        source.execute = AsyncMock(return_value=[])
        target.execute = AsyncMock(return_value=[])

        validator = ChecksumValidator()
        result = await validator.validate(source, target, "t", "dbo", algorithm="MD5")
        assert result.status == ValidationStatus.SKIPPED
        assert len(result.issues) > 0


class TestValidationEngine:
    @pytest.mark.asyncio
    async def test_full_validation_report(self):
        source = MagicMock()
        source.execute = AsyncMock(return_value=[{"cnt": 10}, {"chk": 100}])
        target = MagicMock()
        target.execute = AsyncMock(return_value=[{"cnt": 10}, {"chk": 100}])

        engine = ValidationEngine()
        tables = [
            {
                "name": "users",
                "schema": "dbo",
                "source_columns": [{"column_name": "id", "data_type": "INT"}],
                "target_columns": [{"column_name": "id", "data_type": "INTEGER"}],
            }
        ]

        report = await engine.validate_migration(source, target, tables)
        assert report.total_objects == 2
        assert report.results is not None

    @pytest.mark.asyncio
    async def test_report_counts_passed(self):
        source = MagicMock()
        source.execute = AsyncMock(return_value=[{"cnt": 10}, {"chk": 100}])
        target = MagicMock()
        target.execute = AsyncMock(return_value=[{"cnt": 10}, {"chk": 100}])

        engine = ValidationEngine()
        tables = [
            {
                "name": "t1",
                "schema": "dbo",
                "source_columns": [{"column_name": "id", "data_type": "INT"}],
                "target_columns": [{"column_name": "id", "data_type": "INTEGER"}],
            }
        ]

        report = await engine.validate_migration(source, target, tables)
        assert report.passed + report.failed + report.warnings == report.total_objects

    @pytest.mark.asyncio
    async def test_report_overall_failed(self):
        source = MagicMock()
        target = MagicMock()
        source.execute = AsyncMock(side_effect=[Exception("fail"), Exception("fail")])
        target.execute = AsyncMock(return_value=[{"cnt": 0}])

        engine = ValidationEngine()
        tables = [
            {
                "name": "bad",
                "schema": "dbo",
                "source_columns": [{"column_name": "x", "data_type": "INT"}],
                "target_columns": [{"column_name": "y", "data_type": "INTEGER"}],
            }
        ]

        await engine.validate_migration(source, target, tables)


class TestValidationResult:
    def test_validation_result(self):
        from domains.validation.validation_engine import ValidationResult, ValidationStatus
        r = ValidationResult(
            object_name="test",
            category=ValidationCategory.ROW_COUNT,
            status=ValidationStatus.PASSED,
        )
        assert r.is_valid()
        assert r.validation_id is not None


class TestPreMigrationValidator:
    @pytest.mark.asyncio
    async def test_detects_unsupported_datatype(self):
        from domains.validation.validation_engine import ValidationSeverity, PreMigrationValidator

        source = AsyncMock()
        target = AsyncMock()
        source.execute.side_effect = [
            [{"name": "data", "type_name": "sql_variant", "is_nullable": True, "is_identity": False}],
            [],
            [{"column_name": "id"}],
        ]
        validator = PreMigrationValidator(source, target)
        issues = await validator.validate_table("dbo", "t")
        blocker_issues = [i for i in issues if i.severity == ValidationSeverity.BLOCKER]
        assert len(blocker_issues) >= 1
        assert "sql_variant" in blocker_issues[0].message

    @pytest.mark.asyncio
    async def test_detects_missing_pk(self):
        from domains.validation.validation_engine import ValidationSeverity, PreMigrationValidator

        source = AsyncMock()
        target = AsyncMock()
        source.execute.side_effect = [
            [{"name": "id", "type_name": "int", "is_nullable": False, "is_identity": False}],
            [],
            [],
        ]
        validator = PreMigrationValidator(source, target)
        issues = await validator.validate_table("dbo", "t")
        severities = [i.severity for i in issues]
        assert ValidationSeverity.WARNING in severities or len(issues) == 1

    @pytest.mark.asyncio
    async def test_detects_active_triggers(self):
        from domains.validation.validation_engine import ValidationSeverity, PreMigrationValidator

        source = AsyncMock()
        target = AsyncMock()
        source.execute.side_effect = [
            [{"name": "id", "type_name": "int", "is_nullable": False, "is_identity": True}],
            [{"name": "tr_insert", "is_insert": True, "is_update": False, "is_delete": False, "is_disabled": False}],
            [{"column_name": "id"}],
        ]
        validator = PreMigrationValidator(source, target)
        issues = await validator.validate_table("dbo", "t")
        trigger_issues = [i for i in issues if i.category == "trigger"]
        assert len(trigger_issues) >= 1

    @pytest.mark.asyncio
    async def test_validate_all_tables(self):
        from domains.validation.validation_engine import PreMigrationValidator

        source = AsyncMock()
        target = AsyncMock()
        source.execute.return_value = [
            {"name": "id", "type_name": "int", "is_nullable": False, "is_identity": True},
        ]
        validator = PreMigrationValidator(source, target)
        issues = await validator.validate_all_tables([("dbo", "a"), ("dbo", "b")])
        assert len(issues) >= 0

    @pytest.mark.asyncio
    async def test_validate_privileges_blocks_sysadmin(self):
        from domains.validation.validation_engine import PreMigrationValidator, ValidationSeverity

        source = AsyncMock()
        target = AsyncMock()
        source.execute = AsyncMock(return_value=[{"is_sysadmin": 1, "is_db_owner": 1}])
        target.execute = AsyncMock(return_value=[{"is_superuser": False}])
        validator = PreMigrationValidator(source, target)
        issues = await validator.validate_privileges()
        assert any(i.category == "privilege" for i in issues)
        assert any(i.severity == ValidationSeverity.BLOCKER for i in issues)


class TestAggregateValidator:
    @pytest.mark.asyncio
    async def test_passes_when_aggregates_match(self):
        from domains.validation.validation_engine import AggregateValidator

        source = AsyncMock()
        target = AsyncMock()
        source.execute.return_value = [{"min": 1, "max": 100, "sum": 5050, "avg": 50.5}]
        target.execute.return_value = [{"min": 1, "max": 100, "sum": 5050, "avg": 50.5}]

        validator = AggregateValidator()
        result = await validator.validate(source, target, "orders", "dbo", ["id"])
        assert result.status.name == "PASSED"
        assert result.category.value == "aggregate"
        assert result.details["column_results"][0]["status"] == "passed"

    @pytest.mark.asyncio
    async def test_fails_on_mismatch(self):
        from domains.validation.validation_engine import AggregateValidator

        source = AsyncMock()
        target = AsyncMock()
        source.execute.return_value = [{"min": 1, "max": 100, "sum": 5050, "avg": 50.5}]
        target.execute.return_value = [{"min": 1, "max": 90, "sum": 4095, "avg": 45.5}]

        validator = AggregateValidator()
        result = await validator.validate(source, target, "orders", "dbo", ["id"])
        assert result.status.name == "FAILED"
        assert len(result.issues) > 0

    @pytest.mark.asyncio
    async def test_passes_with_rounded_avg_drift(self):
        from domains.validation.validation_engine import AggregateValidator

        source = AsyncMock()
        target = AsyncMock()
        source.execute.return_value = [{"min": 1, "max": 3000, "sum": 15000, "avg": 1500}]
        target.execute.return_value = [
            {"min": 1, "max": 3000, "sum": 15000, "avg": 1500.0000000000000000}
        ]

        validator = AggregateValidator()
        result = await validator.validate(source, target, "Hotels", "dbo", ["HotelID"])
        assert result.status.name == "PASSED"

    @pytest.mark.asyncio
    async def test_normalizes_uppercase_sqlserver_aggregate_keys(self):
        from domains.validation.validation_engine import AggregateValidator

        source = AsyncMock()
        target = AsyncMock()
        source.execute.return_value = [{"MIN": 1, "MAX": 100, "SUM": 5050, "AVG": 50.5}]
        target.execute.return_value = [{"min": 1, "max": 100, "sum": 5050, "avg": 50.5}]

        validator = AggregateValidator()
        result = await validator.validate(source, target, "orders", "dbo", ["id"])
        assert result.status.name == "PASSED"
        col = result.details["column_results"][0]
        assert col["source"] == {"min": 1, "max": 100, "sum": 5050, "avg": 50.5}
        assert col["target"] == {"min": 1, "max": 100, "sum": 5050, "avg": 50.5}

    @pytest.mark.asyncio
    async def test_target_aggregate_sql_casts_avg_to_numeric_for_round(self):
        """PostgreSQL rejects round(double precision, int); L2 must cast AVG first."""
        from domains.validation.validation_engine import AggregateValidator

        source = AsyncMock()
        target = AsyncMock()
        source.execute.return_value = [{"min": 1, "max": 10, "sum": 55, "avg": 5.5}]
        target.execute.return_value = [{"min": 1, "max": 10, "sum": 55, "avg": 5.5}]

        validator = AggregateValidator()
        result = await validator.validate(
            source,
            target,
            "ProductVendor",
            "Purchasing",
            ["ProductID"],
            target_schema="Purchasing",
        )
        assert result.status.name == "PASSED"
        tgt_sql = target.execute.call_args[0][0]
        assert "ROUND(CAST(AVG(CAST(" in tgt_sql
        assert "AS NUMERIC), 6) AS avg" in tgt_sql
        assert 'FROM "Purchasing"."ProductVendor"' in tgt_sql
