"""
Module: test_compatibility_analyzer.py
Purpose: Unit tests for compatibility analyzer
Author: Migration Platform Team
Created: 2026-05-22
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from uuid import uuid4

import pytest

from domains.transpilation.compatibility_analyzer import CompatibilityAnalyzer
from shared.kernel.database_object import (
    Column,
    CompatibilityStatus,
    DatabaseObject,
    DatabaseObjectType,
    DataType,
    Table,
)


@pytest.fixture
def analyzer():
    return CompatibilityAnalyzer()


@pytest.fixture
def simple_table():
    return Table(
        database_name="test_db",
        schema_name="dbo",
        object_name="users",
        columns=[
            Column(
                table_id=uuid4(),
                column_name="id",
                ordinal_position=1,
                data_type=DataType(type_name="INT"),
                is_identity=True,
            ),
            Column(
                table_id=uuid4(),
                column_name="name",
                ordinal_position=2,
                data_type=DataType(type_name="VARCHAR", max_length=100),
            ),
        ],
    )


class TestCompatibilityAnalyzer:
    def test_analyze_simple_table_auto_convertible(self, analyzer, simple_table):
        result = analyzer.analyze_object(simple_table)
        assert result.status == CompatibilityStatus.AUTO_CONVERTIBLE

    def test_analyze_procedure_partial(self, analyzer):
        proc = DatabaseObject(
            object_type=DatabaseObjectType.PROCEDURE,
            database_name="test_db",
            schema_name="dbo",
            object_name="usp_test",
            source_definition="CREATE PROCEDURE usp_test AS BEGIN TRY SELECT 1 END TRY BEGIN CATCH SELECT 2 END CATCH",
        )
        result = analyzer.analyze_object(proc)
        assert result.status == CompatibilityStatus.PARTIAL

    def test_analyze_unsupported_clr(self, analyzer):
        obj = DatabaseObject(
            object_type=DatabaseObjectType.PROCEDURE,
            database_name="db",
            schema_name="dbo",
            object_name="clr_proc",
            source_definition="CREATE PROCEDURE clr_proc AS EXTERNAL NAME Assembly.Class.Method",
        )
        result = analyzer.analyze_object(obj)
        assert result.status == CompatibilityStatus.UNSUPPORTED

    def test_detect_dynamic_sql(self, analyzer):
        obj = DatabaseObject(
            object_type=DatabaseObjectType.PROCEDURE,
            database_name="db",
            schema_name="dbo",
            object_name="usp_dynamic",
            source_definition="EXEC(@sql)",
        )
        result = analyzer.analyze_object(obj)
        assert len(result.issues) > 0
        assert any("Dynamic SQL" in i.message for i in result.issues)

    def test_detect_risky_type(self, analyzer):
        table = Table(
            database_name="db",
            schema_name="dbo",
            object_name="risky_table",
            columns=[
                Column(
                    table_id=uuid4(),
                    column_name="data",
                    ordinal_position=1,
                    data_type=DataType(type_name="SQL_VARIANT"),
                ),
            ],
        )
        result = analyzer.analyze_object(table)
        assert any("Risky data type" in i.message for i in result.issues)

    def test_batch_analysis(self, analyzer, simple_table):
        proc = DatabaseObject(
            object_type=DatabaseObjectType.PROCEDURE,
            database_name="db",
            schema_name="dbo",
            object_name="usp_test",
        )
        results = analyzer.analyze_batch([simple_table, proc])
        assert len(results) == 2

    def test_report_summary(self, analyzer, simple_table):
        proc = DatabaseObject(
            object_type=DatabaseObjectType.PROCEDURE,
            database_name="db",
            schema_name="dbo",
            object_name="usp_test",
        )
        results = analyzer.analyze_batch([simple_table, proc])
        summary = analyzer.generate_report_summary(results)
        assert summary["total_objects"] == 2
        assert "auto_convertible" in summary
        assert "auto_convertible_percentage" in summary

    def test_issue_collection(self, analyzer):
        obj = DatabaseObject(
            object_type=DatabaseObjectType.PROCEDURE,
            database_name="db",
            schema_name="dbo",
            object_name="usp_complex",
            source_definition="MERGE INTO target USING source ON cond WHEN MATCHED THEN UPDATE SET x = 1;",
        )
        result = analyzer.analyze_object(obj)
        issues = [i for i in result.issues if "MERGE" in i.message]
        assert len(issues) > 0
