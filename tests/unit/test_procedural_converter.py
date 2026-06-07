"""
Module: test_procedural_converter.py
Purpose: Unit tests for procedural code converter
Author: Migration Platform Team
Created: 2026-05-22
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

import pytest

from domains.transpilation.procedural_converter import (
    ConversionDifficulty,
    DynamicSqlAnalyzer,
    ObjectType,
    ParameterInfo,
    ProceduralConverter,
    ProceduralObject,
    TsqlFunctionMapper,
    TSqlPatternMatcher,
)


class TestParameterInfo:
    def test_create_input_param(self):
        p = ParameterInfo(name="p_id", data_type="INT")
        assert p.name == "p_id"
        assert p.is_output is False

    def test_create_output_param(self):
        p = ParameterInfo(name="p_result", data_type="VARCHAR(100)", is_output=True)
        assert p.is_output is True

    def test_param_with_default(self):
        p = ParameterInfo(name="p_name", data_type="VARCHAR(50)", default_value="'N/A'")
        assert p.default_value == "'N/A'"


class TestProceduralObject:
    def test_create_procedure(self):
        obj = ProceduralObject(
            object_type=ObjectType.PROCEDURE,
            schema_name="dbo",
            object_name="usp_test",
        )
        assert obj.object_name == "usp_test"
        assert obj.difficulty == ConversionDifficulty.SIMPLE


class TestTSqlPatternMatcher:
    def test_detect_simple(self):
        diff = TSqlPatternMatcher.detect_difficulty("SELECT * FROM users")
        assert diff == ConversionDifficulty.SIMPLE

    def test_detect_dynamic_sql(self):
        diff = TSqlPatternMatcher.detect_difficulty("EXEC(@sql)")
        assert diff == ConversionDifficulty.COMPLEX

    def test_detect_cursor(self):
        diff = TSqlPatternMatcher.detect_difficulty("DECLARE c CURSOR FOR SELECT * FROM users")
        assert diff == ConversionDifficulty.COMPLEX

    def test_detect_sp_executesql(self):
        diff = TSqlPatternMatcher.detect_difficulty("sp_executesql @sql")
        assert diff == ConversionDifficulty.EXTREME

    def test_detect_try_catch(self):
        diff = TSqlPatternMatcher.detect_difficulty("BEGIN TRY SELECT 1 END TRY BEGIN CATCH END CATCH")
        assert diff == ConversionDifficulty.MODERATE

    def test_detect_patterns(self):
        patterns = TSqlPatternMatcher.detect_patterns("EXEC(@sql); MERGE target USING source;")
        assert "EXEC" in patterns
        assert "MERGE" in patterns

    def test_detect_no_patterns(self):
        patterns = TSqlPatternMatcher.detect_patterns("SELECT 1")
        assert len(patterns) == 0


class TestTsqlFunctionMapper:
    def test_getdate_mapping(self):
        assert TsqlFunctionMapper.FUNCTION_MAP["GETDATE"] == "NOW"

    def test_isnull_mapping(self):
        assert TsqlFunctionMapper.FUNCTION_MAP["ISNULL"] == "COALESCE"

    def test_newid_mapping(self):
        assert TsqlFunctionMapper.FUNCTION_MAP["NEWID"] == "gen_random_uuid"

    def test_len_mapping(self):
        assert TsqlFunctionMapper.FUNCTION_MAP["LEN"] == "LENGTH"

    def test_system_function_mappings(self):
        assert TsqlFunctionMapper.FUNCTION_MAP["DB_NAME"] == "CURRENT_DATABASE"
        assert TsqlFunctionMapper.FUNCTION_MAP["SCOPE_IDENTITY"] == "LASTVAL"

    def test_mappings_exist_for_common_functions(self):
        common = ["GETDATE", "NEWID", "LEN", "ISNULL", "CHARINDEX", "UPPER", "LOWER"]
        for fn in common:
            assert fn in TsqlFunctionMapper.FUNCTION_MAP


class TestProceduralConverter:
    @pytest.fixture
    def converter(self):
        return ProceduralConverter()

    def test_convert_simple_procedure(self, converter):
        result = converter.convert_procedure(
            schema="dbo",
            name="usp_get_users",
            parameters=[
                ParameterInfo(name="p_id", data_type="INT"),
            ],
            body="SELECT * FROM users WHERE id = p_id;",
        )
        assert result.success is True
        assert "CREATE OR REPLACE PROCEDURE" in result.converted_sql
        assert "usp_get_users" in result.converted_sql

    def test_convert_procedure_with_output_param(self, converter):
        result = converter.convert_procedure(
            schema="dbo",
            name="usp_get_count",
            parameters=[
                ParameterInfo(name="p_count", data_type="INT", is_output=True),
            ],
            body="SET p_count = (SELECT COUNT(*) FROM users);",
        )
        assert result.success is True
        assert "INOUT" in result.converted_sql or "p_count" in result.converted_sql

    def test_convert_simple_function(self, converter):
        result = converter.convert_function(
            schema="dbo",
            name="fn_add",
            parameters=[
                ParameterInfo(name="a", data_type="INT"),
                ParameterInfo(name="b", data_type="INT"),
            ],
            body="RETURN a + b;",
            return_type="INTEGER",
        )
        assert result.success is True
        assert "CREATE OR REPLACE FUNCTION" in result.converted_sql
        assert "RETURNS INTEGER" in result.converted_sql

    def test_convert_trigger(self, converter):
        result = converter.convert_trigger(
            schema="dbo",
            name="trg_users_audit",
            table_name="users",
            timing="AFTER",
            event="INSERT OR UPDATE",
            body="INSERT INTO audit_log(table_name, action) VALUES('users', 'modified');",
        )
        assert result.success is True
        assert "CREATE TRIGGER" in result.converted_sql
        assert "trg_users_audit" in result.converted_sql
        assert "EXECUTE FUNCTION" in result.converted_sql

    def test_convert_empty_body(self, converter):
        result = converter.convert_procedure(
            schema="dbo",
            name="usp_empty",
            parameters=[],
            body="",
        )
        assert result.success is True

    def test_warning_for_complex_patterns(self, converter):
        result = converter.convert_procedure(
            schema="dbo",
            name="usp_complex",
            parameters=[],
            body="DECLARE c CURSOR FOR SELECT * FROM users; OPEN c; FETCH c;",
        )
        assert len(result.warnings) > 0


class TestDynamicSqlAnalyzer:
    @pytest.fixture
    def analyzer(self):
        return DynamicSqlAnalyzer()

    def test_no_dynamic_sql(self, analyzer):
        occurrences = analyzer.analyze("SELECT * FROM users")
        assert len(occurrences) == 0

    def test_detect_exec_concat(self, analyzer):
        occurrences = analyzer.analyze("EXEC('SELECT * FROM ' + @table)")
        assert len(occurrences) >= 1
        assert occurrences[0].risk_level == "high"

    def test_detect_sp_executesql(self, analyzer):
        occurrences = analyzer.analyze("sp_executesql @sql, @params, @p1")
        assert len(occurrences) >= 1
        assert occurrences[0].risk_level == "medium"

    def test_detect_simple_exec(self, analyzer):
        occurrences = analyzer.analyze("EXEC usp_get_users")
        assert len(occurrences) >= 1
        assert occurrences[0].risk_level == "low"

    def test_remediation_generation(self, analyzer):
        occurrences = analyzer.analyze("EXEC('SELECT * FROM ' + @table)")
        suggestions = analyzer.generate_remediation(occurrences)
        assert len(suggestions) > 0
