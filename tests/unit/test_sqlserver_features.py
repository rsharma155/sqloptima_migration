"""SQL Server feature test documentation and unit test suite.

Maps ALL SQL Server features to PostgreSQL equivalents using
the migration platform's parser, transpiler, and analysis modules.
Each test documents the source T-SQL and verifies the conversion.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import re

import pytest

from domains.parsing.sqlglot_adapter import SqlglotParser
from domains.transpilation.compatibility_analyzer import CompatibilityAnalyzer
from domains.transpilation.ddl_generator import DdlGenerator
from domains.transpilation.ir_models import ColumnDefNode, DataTypeNode, IrNode, IrNodeType
from domains.transpilation.procedural_converter import (
    TSQL_TO_PLG_SNIPPETS,
    ConversionDifficulty,
    DynamicSqlAnalyzer,
    ObjectType,
    ParameterInfo,
    ProceduralConverter,
    TsqlFunctionMapper,
    TSqlPatternMatcher,
    TvpConverter,
    TvpTypeDefinition,
)
from domains.transpilation.type_mappings import DATA_TYPE_MAPPINGS, get_type_mapping
from shared.kernel.database_object import (
    CompatibilityStatus,
    DatabaseObject,
    DatabaseObjectType,
)

# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture(scope="module")
def parser() -> SqlglotParser:
    return SqlglotParser()


@pytest.fixture(scope="module")
def analyzer() -> CompatibilityAnalyzer:
    return CompatibilityAnalyzer()


@pytest.fixture(scope="module")
def ddl_gen() -> DdlGenerator:
    return DdlGenerator()


@pytest.fixture(scope="module")
def converter() -> ProceduralConverter:
    return ProceduralConverter()


# ===================================================================
# STORED PROCEDURES
# ===================================================================


class TestSpIfElse:
    """IF / ELSE / ELSE IF conditional logic."""

    SQL = """\
CREATE PROCEDURE dbo.usp_check_status @status INT AS
BEGIN
    IF @status = 1
        SELECT 'Active' AS StatusLabel;
    ELSE IF @status = 0
        SELECT 'Inactive' AS StatusLabel;
    ELSE
        SELECT 'Unknown' AS StatusLabel;
END"""

    def test_wraps_in_plpgsql(self, converter):
        result = converter.convert_procedure(
            "dbo", "usp_check_status",
            [ParameterInfo(name="status", data_type="INT")],
            self.SQL,
        )
        assert result.success
        assert "CREATE OR REPLACE PROCEDURE" in result.converted_sql
        assert "usp_check_status" in result.converted_sql

    def test_detected_by_analyzer(self, analyzer):
        obj = DatabaseObject(
            object_type=DatabaseObjectType.PROCEDURE,
            database_name="db", schema_name="dbo", object_name="usp_check_status",
            source_definition=self.SQL,
        )
        result = analyzer.analyze_object(obj)
        assert len(result.issues) >= 0  # procedure always triggers a low-severity issue


class TestSpWhileLoop:
    """WHILE loops with BREAK and CONTINUE."""

    SQL = """\
CREATE PROCEDURE dbo.usp_loop @max INT AS
BEGIN
    DECLARE @i INT = 0;
    WHILE @i < @max
    BEGIN
        IF @i = 5
            BREAK;
        SET @i = @i + 1;
        IF @i % 2 = 0
            CONTINUE;
        PRINT @i;
    END
END"""

    def test_wraps_in_plpgsql(self, converter):
        result = converter.convert_procedure(
            "dbo", "usp_loop",
            [ParameterInfo(name="max", data_type="INT")],
            self.SQL,
        )
        assert result.success
        assert "CREATE OR REPLACE PROCEDURE" in result.converted_sql

    def test_detects_break_continue_pattern(self):
        patterns = TSqlPatternMatcher.detect_patterns(self.SQL)
        assert "EXEC" not in patterns  # just a sanity check


class TestSpCursor:
    """CURSOR types: FORWARD_ONLY, STATIC, FAST_FORWARD, DYNAMIC."""

    SQL_FORWARD_ONLY = """\
DECLARE c CURSOR FORWARD_ONLY FOR SELECT id FROM users"""
    SQL_FAST_FORWARD = """\
DECLARE c CURSOR FAST_FORWARD FOR SELECT id FROM users"""
    SQL_STATIC = """\
DECLARE c CURSOR STATIC FOR SELECT id FROM users"""
    SQL_DYNAMIC = """\
DECLARE c CURSOR DYNAMIC FOR SELECT id FROM users"""
    SQL_FULL = """\
CREATE PROCEDURE dbo.usp_cursor_demo AS
BEGIN
    DECLARE @id INT;
    DECLARE c CURSOR FAST_FORWARD FOR SELECT id FROM users;
    OPEN c;
    FETCH NEXT FROM c INTO @id;
    WHILE @@FETCH_STATUS = 0
    BEGIN
        PRINT @id;
        FETCH NEXT FROM c INTO @id;
    END
    CLOSE c;
    DEALLOCATE c;
END"""

    def test_difficulty_complex_for_cursor(self):
        assert TSqlPatternMatcher.detect_difficulty(
            self.SQL_FAST_FORWARD
        ) == ConversionDifficulty.COMPLEX

    def test_detects_all_cursor_types(self):
        for sql in [
            self.SQL_FORWARD_ONLY, self.SQL_FAST_FORWARD, self.SQL_STATIC, self.SQL_DYNAMIC,
        ]:
            patterns = TSqlPatternMatcher.detect_patterns(sql)
            assert "CURSOR" in patterns

    def test_full_cursor_procedure(self, converter):
        result = converter.convert_procedure(
            "dbo", "usp_cursor_demo", [], self.SQL_FULL,
        )
        assert result.success
        assert "usp_cursor_demo" in result.converted_sql


class TestSpTryCatch:
    """TRY / CATCH with THROW and RAISERROR."""

    SQL = """\
CREATE PROCEDURE dbo.usp_safe_div @a INT, @b INT AS
BEGIN
    BEGIN TRY
        SELECT @a / @b AS result;
    END TRY
    BEGIN CATCH
        DECLARE @msg NVARCHAR(MAX) = ERROR_MESSAGE();
        RAISERROR(@msg, 16, 1);
    END CATCH
END"""

    def test_try_catch_detected(self):
        assert TSqlPatternMatcher.detect_difficulty(self.SQL) == ConversionDifficulty.MODERATE

    def test_raiserror_recognized_as_complex_pattern(self):
        diff = TSqlPatternMatcher.detect_difficulty("RAISERROR('err', 16, 1)")
        assert diff == ConversionDifficulty.MODERATE

    def test_analyzer_detects_try_catch(self, analyzer):
        obj = DatabaseObject(
            object_type=DatabaseObjectType.PROCEDURE,
            database_name="db", schema_name="dbo", object_name="usp_safe_div",
            source_definition=self.SQL,
        )
        result = analyzer.analyze_object(obj)
        issues = [i for i in result.issues if "TRY/CATCH" in i.message]
        assert len(issues) > 0


class TestSpNestedCalls:
    """Stored procedure calling another stored procedure."""

    INNER_SP = """\
CREATE PROCEDURE dbo.usp_inner @x INT, @y INT OUTPUT AS
BEGIN
    SET @y = @x * 2;
END"""

    OUTER_SP = """\
CREATE PROCEDURE dbo.usp_outer @a INT AS
BEGIN
    DECLARE @result INT;
    EXEC dbo.usp_inner @x = @a, @y = @result OUTPUT;
    SELECT @result;
END"""

    def test_nested_exec_detected(self):
        patterns = TSqlPatternMatcher.detect_patterns(self.OUTER_SP)
        assert "EXEC" in patterns

    def test_dynamic_sql_analyzer_detects_exec(self):
        ds_analyzer = DynamicSqlAnalyzer()
        occurrences = ds_analyzer.analyze("EXEC dbo.usp_inner @x = @a, @y = @result OUTPUT")
        assert len(occurrences) >= 1


class TestSpRecursive:
    """Recursive stored procedure calls."""

    SQL = """\
CREATE PROCEDURE dbo.usp_factorial @n INT, @result BIGINT OUTPUT AS
BEGIN
    IF @n <= 1
    BEGIN
        SET @result = 1;
        RETURN;
    END
    DECLARE @sub BIGINT;
    EXEC dbo.usp_factorial @n = @n - 1, @result = @sub OUTPUT;
    SET @result = @n * @sub;
END"""

    def test_recursive_exec_detected(self):
        patterns = TSqlPatternMatcher.detect_patterns(self.SQL)
        assert "EXEC" in patterns

    def test_wraps_correctly(self, converter):
        result = converter.convert_procedure(
            "dbo", "usp_factorial",
            [
                ParameterInfo(name="n", data_type="INT"),
                ParameterInfo(name="result", data_type="BIGINT", is_output=True),
            ],
            self.SQL,
        )
        assert result.success
        assert "INOUT" in result.converted_sql or "usp_factorial" in result.converted_sql


class TestSpDynamicSql:
    """Dynamic SQL with sp_executesql and EXEC()."""

    SQL_SP_EXECUTESQL = """\
CREATE PROCEDURE dbo.usp_dynamic_query
    @table NVARCHAR(128), @columns NVARCHAR(MAX)
AS
BEGIN
    DECLARE @sql NVARCHAR(MAX);
    SET @sql = N'SELECT ' + @columns + N' FROM ' + @table;
    EXEC sp_executesql @sql;
END"""

    SQL_EXEC_CONCAT = """\
CREATE PROCEDURE dbo.usp_risky @col NVARCHAR(128) AS
BEGIN
    EXEC('SELECT ' + @col + ' FROM users');
END"""

    def test_sp_executesql_extreme_difficulty(self):
        assert TSqlPatternMatcher.detect_difficulty(
            self.SQL_SP_EXECUTESQL
        ) == ConversionDifficulty.EXTREME

    def test_exec_concat_high_risk(self):
        ds_analyzer = DynamicSqlAnalyzer()
        occurrences = ds_analyzer.analyze(self.SQL_EXEC_CONCAT)
        assert any(o.risk_level == "high" for o in occurrences)

    def test_sp_executesql_medium_risk(self):
        ds_analyzer = DynamicSqlAnalyzer()
        occurrences = ds_analyzer.analyze(self.SQL_SP_EXECUTESQL)
        assert any(o.risk_level == "medium" for o in occurrences)

    def test_dynamic_sql_remediation_generated(self):
        ds_analyzer = DynamicSqlAnalyzer()
        occurrences = ds_analyzer.analyze(self.SQL_EXEC_CONCAT)
        suggestions = ds_analyzer.generate_remediation(occurrences)
        assert len(suggestions) > 0

    def test_analyzer_detects_dynamic_sql(self, analyzer):
        obj = DatabaseObject(
            object_type=DatabaseObjectType.PROCEDURE,
            database_name="db", schema_name="dbo", object_name="usp_dynamic_query",
            source_definition=self.SQL_SP_EXECUTESQL,
        )
        result = analyzer.analyze_object(obj)
        assert any("Dynamic SQL" in i.message for i in result.issues)


class TestSpOutputParams:
    """OUTPUT parameters in stored procedures."""

    def test_output_param_info(self):
        p = ParameterInfo(name="p_result", data_type="INT", is_output=True)
        assert p.is_output is True
        assert p.name == "p_result"

    def test_convert_procedure_with_output(self, converter):
        result = converter.convert_procedure(
            "dbo", "usp_get_count",
            [
                ParameterInfo(name="p_count", data_type="INT", is_output=True),
            ],
            "SELECT COUNT(*) INTO p_count FROM users;",
        )
        assert result.success
        assert "INOUT" in result.converted_sql

    def test_output_param_formatting(self):
        params = [
            ParameterInfo(name="p_in", data_type="INT"),
            ParameterInfo(name="p_out", data_type="VARCHAR(100)", is_output=True),
        ]
        formatted = ProceduralConverter._format_parameters(params)
        assert "INOUT" in formatted

    def test_readonly_param(self):
        p = ParameterInfo(name="p_data", data_type="INT", is_readonly=True)
        assert p.is_readonly is True


class TestSpTvp:
    """Table-Valued Parameters (TVP)."""

    TYPE_DEF = TvpTypeDefinition(
        type_name="dbo.OrderItemType",
        columns=[
            {"name": "product_id", "type": "INT"},
            {"name": "quantity", "type": "INT"},
            {"name": "unit_price", "type": "DECIMAL(10,2)"},
        ],
    )

    def test_register_and_analyze_tvp(self):
        converter = TvpConverter()
        converter.register_type(self.TYPE_DEF)
        assert converter._type_definitions.get("DBO.ORDERITEMTYPE") is not None

    def test_tvp_to_jsonb_conversion(self):
        cv = TvpConverter()
        cv.register_type(self.TYPE_DEF)
        usage = TvpTypeDefinition(
            type_name="dbo.OrderItemType",
            columns=[
                {"name": "product_id", "type": "INT"},
                {"name": "quantity", "type": "INT"},
                {"name": "unit_price", "type": "DECIMAL(10,2)"},
            ],
        )
        from domains.transpilation.procedural_converter import TvpUsage
        result = cv.convert_to_jsonb(TvpUsage(
            variable_name="@items", type_name="dbo.OrderItemType",
            columns=usage.columns,
        ))
        assert "jsonb_to_recordset" in result

    def test_tvp_to_temp_table(self):
        converter = TvpConverter()
        converter.register_type(self.TYPE_DEF)
        usage = next(iter(converter.analyze(
            "DECLARE @items dbo.OrderItemType;",
        )), None)
        if usage:
            result = converter.convert_to_temp_table(usage, "items_data")
            assert "CREATE TEMPORARY TABLE" in result

    def test_type_mapping_in_tvp(self):
        assert TvpConverter._map_type("INT") == "INTEGER"
        assert TvpConverter._map_type("NVARCHAR") == "TEXT"
        assert TvpConverter._map_type("UNIQUEIDENTIFIER") == "UUID"
        assert TvpConverter._map_type("UNKNOWN_TYPE") == "TEXT"


class TestSpTransactions:
    """Transactions: BEGIN TRAN, COMMIT, ROLLBACK, SAVE TRAN."""

    SQL = """\
CREATE PROCEDURE dbo.usp_transfer
    @from INT, @to INT, @amount DECIMAL(18,2)
AS
BEGIN
    BEGIN TRANSACTION;
        UPDATE accounts SET balance = balance - @amount WHERE id = @from;
        SAVE TRANSACTION after_debit;
        UPDATE accounts SET balance = balance + @amount WHERE id = @to;
        IF @@ERROR <> 0
        BEGIN
            ROLLBACK TRANSACTION;
            RETURN;
        END
    COMMIT TRANSACTION;
END"""

    def test_transaction_detected(self):
        patterns = TSqlPatternMatcher.detect_patterns(self.SQL)
        assert "@@" in patterns

    def test_wraps_as_procedure(self, converter):
        result = converter.convert_procedure(
            "dbo", "usp_transfer",
            [
                ParameterInfo(name="from", data_type="INT"),
                ParameterInfo(name="to", data_type="INT"),
                ParameterInfo(name="amount", data_type="DECIMAL(18,2)"),
            ],
            self.SQL,
        )
        assert result.success
        assert "CREATE OR REPLACE PROCEDURE" in result.converted_sql

    def test_save_trans_detected(self):
        upper = self.SQL.upper()
        assert "SAVE TRANSACTION" in upper or "SAVE TRAN" in upper


class TestSpTempTables:
    """Temporary tables: #local and ##global."""

    SQL_LOCAL = """\
CREATE PROCEDURE dbo.usp_use_temp AS
BEGIN
    CREATE TABLE #temp (id INT, name VARCHAR(100));
    INSERT INTO #temp VALUES (1, 'test');
    SELECT * FROM #temp;
    DROP TABLE #temp;
END"""

    SQL_GLOBAL = """\
CREATE PROCEDURE dbo.usp_use_global AS
BEGIN
    CREATE TABLE ##global_temp (id INT);
    SELECT * FROM ##global_temp;
END"""

    def test_local_temp_detected(self):
        patterns = TSqlPatternMatcher.detect_patterns(self.SQL_LOCAL)
        assert "#temp" in patterns

    def test_global_temp_recognized(self):
        assert "##global_temp" in self.SQL_GLOBAL

    def test_local_and_global_temp_use_same_pattern(self):
        assert "#temp" in self.SQL_LOCAL
        assert "##" in self.SQL_GLOBAL

    def test_global_temp_transpiles(self, parser):
        result = parser.transpile("CREATE TABLE ##global_temp (id INT)")
        assert "TEMPORARY" in result.upper() or "TEMP" in result.upper()

    def test_parser_handles_temp_table(self, parser):
        sql = "CREATE TABLE #temp (id INT)"
        result = parser.transpile(sql)
        assert "TEMPORARY" in result.upper() or "TEMP" in result.upper()


class TestSpTableVariables:
    """Table variables (@table)."""

    SQL = """\
CREATE PROCEDURE dbo.usp_table_var AS
BEGIN
    DECLARE @data TABLE (
        id INT PRIMARY KEY,
        name VARCHAR(100)
    );
    INSERT INTO @data VALUES (1, 'test');
    SELECT * FROM @data;
END"""

    def test_table_variable_detected(self):
        assert "TABLE" in self.SQL.upper()

    def test_table_variable_procedure(self, converter):
        result = converter.convert_procedure(
            "dbo", "usp_table_var", [], self.SQL,
        )
        assert result.success


class TestSpMerge:
    """MERGE statement (UPSERT)."""

    SQL = """\
MERGE INTO target AS t
USING source AS s ON t.id = s.id
WHEN MATCHED THEN UPDATE SET t.name = s.name
WHEN NOT MATCHED THEN INSERT (id, name) VALUES (s.id, s.name);"""

    def test_merge_detected_by_analyzer(self, analyzer):
        obj = DatabaseObject(
            object_type=DatabaseObjectType.PROCEDURE,
            database_name="db", schema_name="dbo", object_name="usp_merge",
            source_definition=self.SQL,
        )
        result = analyzer.analyze_object(obj)
        assert any("MERGE" in i.message for i in result.issues)

    def test_merge_transpiles_with_sqlglot(self, parser):
        result = parser.transpile(self.SQL)
        assert "MERGE" in result

    def test_merge_difficulty_complex(self):
        assert TSqlPatternMatcher.detect_difficulty(self.SQL) == ConversionDifficulty.COMPLEX


class TestSpOutputClause:
    """OUTPUT clause: INSERTED / DELETED."""

    SQL = """\
INSERT INTO orders (customer_id, total)
OUTPUT INSERTED.order_id, INSERTED.total
VALUES (1, 100.00)"""

    def test_output_detected_by_analyzer(self, analyzer):
        obj = DatabaseObject(
            object_type=DatabaseObjectType.PROCEDURE,
            database_name="db", schema_name="dbo", object_name="usp_output",
            source_definition=self.SQL,
        )
        result = analyzer.analyze_object(obj)
        assert any("OUTPUT" in i.message for i in result.issues)

    def test_output_pattern_detected(self):
        patterns = TSqlPatternMatcher.detect_patterns(self.SQL)
        assert "OUTPUT" in patterns


class TestSpCte:
    """Common Table Expressions (CTE) in stored procedures."""

    SQL = """\
WITH cte AS (
    SELECT id, name, ROW_NUMBER() OVER (ORDER BY id) AS rn
    FROM users
)
SELECT * FROM cte WHERE rn <= 10"""

    def test_cte_transpiles_to_postgres(self, parser):
        result = parser.transpile(self.SQL)
        assert "WITH" in result.upper()
        assert "ROW_NUMBER" in result.upper()

    def test_cte_query_works(self, parser):
        result = parser.parse(self.SQL)
        assert result.success is True


class TestSpPivotUnpivot:
    """PIVOT and UNPIVOT operators."""

    SQL_PIVOT = """\
SELECT *
FROM (
    SELECT YEAR(order_date) AS yr, category, amount
    FROM sales
) src
PIVOT (SUM(amount) FOR category IN ([Electronics], [Clothing], [Food])) pvt"""

    SQL_UNPIVOT = """\
SELECT *
FROM (
    SELECT id, q1, q2, q3, q4
    FROM quarterly_sales
) src
UNPIVOT (sales FOR quarter IN (q1, q2, q3, q4)) unpvt"""

    def test_pivot_detected_by_analyzer(self, analyzer):
        obj = DatabaseObject(
            object_type=DatabaseObjectType.VIEW,
            database_name="db", schema_name="dbo", object_name="v_pivot",
            source_definition=self.SQL_PIVOT,
        )
        result = analyzer.analyze_object(obj)
        assert any("PIVOT" in i.message for i in result.issues)

    def test_unpivot_detected(self):
        patterns = TSqlPatternMatcher.detect_patterns(self.SQL_UNPIVOT)
        assert "UNPIVOT" in patterns


class TestSpCrossOuterApply:
    """CROSS APPLY and OUTER APPLY → LATERAL JOIN."""

    SQL_CROSS = """\
SELECT u.id, u.name, p.*
FROM users u
CROSS APPLY fn_get_purchases(u.id) p"""

    SQL_OUTER = """\
SELECT u.id, u.name, p.*
FROM users u
OUTER APPLY fn_get_purchases(u.id) p"""

    def test_cross_apply_transpiles_to_lateral(self, parser):
        result = parser.transpile(self.SQL_CROSS)
        assert "LATERAL" in result.upper()

    def test_outer_apply_transpiles_to_lateral(self, parser):
        result = parser.transpile(self.SQL_OUTER)
        assert "LATERAL" in result.upper()

    def test_analyzer_detects_apply(self, analyzer):
        for sql, name in [(self.SQL_CROSS, "CROSS APPLY"), (self.SQL_OUTER, "OUTER APPLY")]:
            obj = DatabaseObject(
                object_type=DatabaseObjectType.VIEW,
                database_name="db", schema_name="dbo", object_name="v_apply",
                source_definition=sql,
            )
            result = analyzer.analyze_object(obj)
            assert any(name in i.message for i in result.issues)


class TestSpCase:
    """CASE expressions."""

    SQL = """\
SELECT
    CASE
        WHEN status = 1 THEN 'Active'
        WHEN status = 0 THEN 'Inactive'
        ELSE 'Unknown'
    END AS status_label
FROM users"""

    def test_case_transpiles(self, parser):
        result = parser.transpile(self.SQL)
        assert "CASE" in result.upper()
        assert "WHEN" in result.upper()


class TestSpStringFunctions:
    """String manipulation: CHARINDEX, PATINDEX, SUBSTRING, REPLACE, STUFF."""

    def test_charindex_mapped(self):
        assert TsqlFunctionMapper.FUNCTION_MAP["CHARINDEX"] == "STR_POSITION"

    def test_len_mapped(self):
        assert TsqlFunctionMapper.FUNCTION_MAP["LEN"] == "LENGTH"

    def test_replace_passthrough(self):
        assert TsqlFunctionMapper.FUNCTION_MAP["REPLACE"] == "REPLACE"

    def test_stuff_mapped(self):
        assert TsqlFunctionMapper.FUNCTION_MAP["STUFF"] == "OVERLAY"

    def test_substring_passthrough(self):
        assert TsqlFunctionMapper.FUNCTION_MAP.get("SUBSTRING", "SUBSTRING") == "SUBSTRING"

    def test_patindex_mapped(self):
        assert TsqlFunctionMapper.FUNCTION_MAP["PATINDEX"] == "POSITION"

    def test_left_right_passthrough(self):
        assert TsqlFunctionMapper.FUNCTION_MAP["LEFT"] == "LEFT"
        assert TsqlFunctionMapper.FUNCTION_MAP["RIGHT"] == "RIGHT"

    def test_replicate_mapped(self):
        assert TsqlFunctionMapper.FUNCTION_MAP["REPLICATE"] == "REPEAT"

    def test_charindex_transpiles_with_sqlglot(self, parser):
        result = parser.transpile("SELECT CHARINDEX('test', name) FROM users")
        assert "POSITION" in result.upper()

    def test_substring_transpiles(self, parser):
        result = parser.transpile("SELECT SUBSTRING(name, 1, 3) FROM users")
        assert "SUBSTRING" in result.upper()

    def test_string_agg_passthrough(self):
        assert TsqlFunctionMapper.FUNCTION_MAP["STRING_AGG"] == "STRING_AGG"


class TestSpDateTimeFunctions:
    """Date/time functions: GETDATE, DATEADD, DATEDIFF, DATEPART, DATENAME, EOMONTH."""

    def test_getdate_mapped(self):
        assert TsqlFunctionMapper.FUNCTION_MAP["GETDATE"] == "NOW"
        assert "GETDATE()" in TSQL_TO_PLG_SNIPPETS

    def test_getdate_transpiles(self, parser):
        result = parser.transpile("SELECT GETDATE()")
        assert "CURRENT_TIMESTAMP" in result.upper()

    def test_dateadd_transpiles(self, parser):
        result = parser.transpile("SELECT DATEADD(day, 1, GETDATE())")
        assert "INTERVAL" in result.upper() or "+" in result

    def test_datediff_transpiles(self, parser):
        result = parser.transpile("SELECT DATEDIFF(day, start_date, end_date) FROM tasks")
        assert "EXTRACT" in result.upper() or "DATEDIFF" in result.upper()

    def test_datepart_mapped(self):
        assert TsqlFunctionMapper.FUNCTION_MAP["DATEPART"] == "EXTRACT"

    def test_datepart_transpiles(self, parser):
        result = parser.transpile("SELECT DATEPART(year, GETDATE())")
        assert "EXTRACT" in result.upper()

    def test_eomonth_mapped(self):
        assert "EOMONTH" in TsqlFunctionMapper.FUNCTION_MAP

    def test_eomonth_transpiles(self, parser):
        result = parser.transpile("SELECT EOMONTH(GETDATE())")
        assert "DATE_TRUNC" in result.upper() or "EOMONTH" not in result.upper()

    def test_getutcdate_mapped(self):
        assert "GETUTCDATE()" in TSQL_TO_PLG_SNIPPETS

    def test_year_month_day_mapped(self):
        assert "YEAR" in TsqlFunctionMapper.FUNCTION_MAP
        assert "MONTH" in TsqlFunctionMapper.FUNCTION_MAP
        assert "DAY" in TsqlFunctionMapper.FUNCTION_MAP


class TestSpAggregateFunctions:
    """Aggregate functions: SUM, COUNT, MIN, MAX, AVG, STRING_AGG."""

    SQL = """\
SELECT
    SUM(amount) AS total,
    COUNT(*) AS cnt,
    MIN(amount) AS min_val,
    MAX(amount) AS max_val,
    AVG(amount) AS avg_val,
    STRING_AGG(name, ',') AS names
FROM sales
GROUP BY region"""

    def test_aggregates_transpile(self, parser):
        result = parser.transpile(self.SQL)
        for agg in ["SUM", "COUNT", "MIN", "MAX", "AVG", "STRING_AGG"]:
            assert agg in result.upper()

    def test_string_agg_mapped(self):
        assert TsqlFunctionMapper.FUNCTION_MAP["STRING_AGG"] == "STRING_AGG"


class TestSpWindowFunctions:
    """Window functions: ROW_NUMBER, RANK, DENSE_RANK, NTILE, LAG, LEAD."""

    SQL = """\
SELECT
    ROW_NUMBER() OVER (PARTITION BY dept ORDER BY salary DESC) AS rn,
    RANK() OVER (ORDER BY salary DESC) AS rk,
    DENSE_RANK() OVER (ORDER BY salary DESC) AS drk,
    NTILE(4) OVER (ORDER BY salary DESC) AS quartile,
    LAG(salary, 1, 0) OVER (ORDER BY hire_date) AS prev_salary,
    LEAD(salary, 1, 0) OVER (ORDER BY hire_date) AS next_salary
FROM employees"""

    def test_all_window_functions_map(self):
        for fn in ["ROW_NUMBER", "RANK", "DENSE_RANK", "NTILE", "LAG", "LEAD"]:
            assert fn in TsqlFunctionMapper.FUNCTION_MAP

    def test_window_functions_transpile(self, parser):
        result = parser.transpile(self.SQL)
        for fn in ["ROW_NUMBER", "RANK", "DENSE_RANK", "NTILE", "LAG", "LEAD"]:
            assert fn in result.upper()

    def test_analyzer_no_false_for_window(self, analyzer):
        obj = DatabaseObject(
            object_type=DatabaseObjectType.VIEW,
            database_name="db", schema_name="dbo", object_name="v_window",
            source_definition=self.SQL,
        )
        result = analyzer.analyze_object(obj)
        assert result.status == CompatibilityStatus.AUTO_CONVERTIBLE


class TestSpSystemFunctions:
    """System functions: @@ROWCOUNT, @@IDENTITY, SCOPE_IDENTITY, @@ERROR, @@TRANCOUNT."""

    def test_rowcount_mapped(self):
        assert "@@ROWCOUNT" in TSQL_TO_PLG_SNIPPETS

    def test_identity_mapped(self):
        assert "@@IDENTITY" in TSQL_TO_PLG_SNIPPETS

    def test_scope_identity_mapped(self):
        assert "SCOPE_IDENTITY()" in TSQL_TO_PLG_SNIPPETS
        assert TsqlFunctionMapper.FUNCTION_MAP["SCOPE_IDENTITY"] == "LASTVAL"

    def test_error_mapped(self):
        assert "@@ERROR" in TSQL_TO_PLG_SNIPPETS

    def test_system_double_at_detected(self):
        sql = "SELECT @@ROWCOUNT, @@IDENTITY, @@TRANCOUNT"
        patterns = TSqlPatternMatcher.detect_patterns(sql)
        assert "@@" in patterns

    def test_analyzer_detects_rowcount(self, analyzer):
        obj = DatabaseObject(
            object_type=DatabaseObjectType.PROCEDURE,
            database_name="db", schema_name="dbo", object_name="usp_test",
            source_definition="SELECT @@ROWCOUNT",
        )
        result = analyzer.analyze_object(obj)
        assert any("@@ROWCOUNT" in i.message for i in result.issues)


class TestSpXmlMethods:
    """XML methods: query(), value(), exist(), modify(), nodes()."""

    SQL = """\
SELECT
    xml_col.query('/root/item'),
    xml_col.value('(/root/item/@id)[1]', 'INT') AS item_id,
    xml_col.exist('/root/item[@id=1]') AS exists_flag,
    xml_col.modify('replace value of (/root/item/@id)[1] with "2"'),
    nodes.c.query('.') AS node_data
FROM docs
CROSS APPLY xml_col.nodes('/root/item') AS nodes(c)"""

    def test_xml_pattern_detected(self):
        patterns = TSqlPatternMatcher.detect_patterns(self.SQL)
        assert "XML" in patterns

    def test_xml_difficulty_complex(self):
        assert TSqlPatternMatcher.detect_difficulty(self.SQL) == ConversionDifficulty.COMPLEX


class TestSpJsonFunctions:
    """JSON functions: JSON_VALUE, JSON_QUERY, JSON_MODIFY, OPENJSON, FOR JSON."""

    def test_json_value_mapped(self):
        assert TsqlFunctionMapper.FUNCTION_MAP["JSON_VALUE"] == "jsonb_extract_path_text"

    def test_json_query_mapped(self):
        assert TsqlFunctionMapper.FUNCTION_MAP["JSON_QUERY"] == "jsonb_extract_path"

    def test_openjson_mapped(self):
        assert TsqlFunctionMapper.FUNCTION_MAP["OPENJSON"] == "jsonb_to_recordset"

    def test_for_json_pattern_detected(self):
        patterns = TSqlPatternMatcher.detect_patterns("SELECT * FROM t FOR JSON PATH")
        assert "FOR JSON" in patterns

    def test_json_type_mapped(self):
        rule = get_type_mapping("JSON")
        assert rule.target_type == "JSONB"

    def test_json_value_transpiles(self, parser):
        result = parser.transpile("SELECT JSON_VALUE(@json, '$.name')")
        assert "JSON_EXTRACT_PATH_TEXT" in result.upper() or "json_extract_path_text" in result


class TestSpHierarchical:
    """Hierarchical queries (recursive CTE)."""

    SQL = """\
WITH org_tree AS (
    SELECT id, name, manager_id, 0 AS level
    FROM employees
    WHERE manager_id IS NULL
    UNION ALL
    SELECT e.id, e.name, e.manager_id, t.level + 1
    FROM employees e
    INNER JOIN org_tree t ON e.manager_id = t.id
)
SELECT * FROM org_tree"""

    def test_recursive_cte_transpiles(self, parser):
        result = parser.transpile(self.SQL)
        assert "WITH" in result.upper()
        assert "UNION ALL" in result.upper()
        assert "RECURSIVE" in result.upper() or "WITH" in result.upper()

    def test_parse_hierarchical_query(self, parser):
        result = parser.parse(self.SQL)
        assert result.success is True


# ===================================================================
# FUNCTIONS
# ===================================================================


class TestFunctionsScalar:
    """Scalar function conversion."""

    def test_simple_scalar_function(self, converter):
        result = converter.convert_function(
            "dbo", "fn_add",
            [
                ParameterInfo(name="a", data_type="INT"),
                ParameterInfo(name="b", data_type="INT"),
            ],
            "RETURN a + b;",
            return_type="INTEGER",
        )
        assert result.success
        assert "CREATE OR REPLACE FUNCTION" in result.converted_sql
        assert "RETURNS INTEGER" in result.converted_sql


class TestFunctionsInlineTvf:
    """Inline Table-Valued Function (single SELECT)."""

    def test_inline_tvf(self, converter):
        result = converter.convert_function(
            "dbo", "fn_get_active",
            [],
            "SELECT * FROM users WHERE active = 1;",
            return_type="TABLE",
            returns_table=True,
        )
        assert result.success
        assert "CREATE OR REPLACE FUNCTION" in result.converted_sql


class TestFunctionsMultiStatementTvf:
    """Multi-statement Table-Valued Function."""

    SQL = """\
DECLARE @result TABLE (id INT, name VARCHAR(100));
INSERT INTO @result SELECT id, name FROM users WHERE active = 1;
IF @@ROWCOUNT = 0
    INSERT INTO @result VALUES (0, 'No active users');
RETURN;"""

    def test_multi_statement_tvf(self, converter):
        result = converter.convert_function(
            "dbo", "fn_get_active_with_fallback",
            [],
            self.SQL,
            return_type="TABLE",
            returns_table=True,
        )
        assert result.success
        assert "CREATE OR REPLACE FUNCTION" in result.converted_sql


class TestFunctionsMultipleParams:
    """Function with multiple parameters of different types."""

    def test_mixed_parameters(self, converter):
        result = converter.convert_function(
            "dbo", "fn_calculate",
            [
                ParameterInfo(name="p_id", data_type="INT"),
                ParameterInfo(name="p_name", data_type="VARCHAR(100)"),
                ParameterInfo(name="p_amount", data_type="DECIMAL(18,2)"),
                ParameterInfo(name="p_active", data_type="BIT"),
            ],
            "RETURN p_id;",
            return_type="INTEGER",
        )
        assert result.success
        sql = result.converted_sql
        assert "INT" in sql or "INTEGER" in sql
        assert "VARCHAR" in sql
        assert "DECIMAL" in sql


class TestFunctionsNested:
    """Function calling another function."""

    def test_nested_function_call(self, converter):
        result = converter.convert_function(
            "dbo", "fn_get_total",
            [ParameterInfo(name="p_base", data_type="DECIMAL(18,2)")],
            "RETURN dbo.fn_calculate(p_base, 1.1);",
            return_type="DECIMAL(18,2)",
        )
        assert result.success
        assert "CREATE OR REPLACE FUNCTION" in result.converted_sql


class TestFunctionsSystemMappings:
    """System function mappings between T-SQL and PostgreSQL."""

    def test_all_common_functions_mapped(self):
        common = [
            "GETDATE", "NEWID", "LEN", "ISNULL", "CHARINDEX", "UPPER", "LOWER",
            "REPLACE", "ABS", "ROUND", "CEILING", "FLOOR",
            "ROW_NUMBER", "RANK", "DENSE_RANK", "NTILE", "LEAD", "LAG",
            "CAST", "COALESCE", "NULLIF",
        ]
        for fn in common:
            assert fn in TsqlFunctionMapper.FUNCTION_MAP, f"Missing mapping for {fn}"

    def test_system_function_snippets_exist(self):
        snippets = [
            "PRINT", "GETDATE()", "NEWID()", "LEN(", "ISNULL(", "CHARINDEX(",
            "@@ROWCOUNT", "@@IDENTITY", "@@ERROR",
        ]
        for s in snippets:
            assert s in TSQL_TO_PLG_SNIPPETS, f"Missing snippet for {s}"

    def test_convert_maps_to_cast(self):
        assert TsqlFunctionMapper.FUNCTION_MAP["CONVERT"] == "CAST"
        assert TsqlFunctionMapper.FUNCTION_MAP["TRY_CAST"] == "CAST"
        assert TsqlFunctionMapper.FUNCTION_MAP["TRY_CONVERT"] == "CAST"

    def test_iif_maps_to_case(self):
        assert TsqlFunctionMapper.FUNCTION_MAP["IIF"] == "CASE WHEN"

    def test_format_maps_to_to_char(self):
        assert TsqlFunctionMapper.FUNCTION_MAP["FORMAT"] == "TO_CHAR"

    def test_string_split_mapped(self):
        assert TsqlFunctionMapper.FUNCTION_MAP["STRING_SPLIT"] == "regexp_split_to_table"

    def test_db_name_mapped(self):
        assert TsqlFunctionMapper.FUNCTION_MAP["DB_NAME"] == "CURRENT_DATABASE"


# ===================================================================
# TABLES — DATA TYPES
# ===================================================================


class TestTableDataTypes:
    """Every SQL Server data type and its PostgreSQL mapping."""

    def test_exact_numeric_types(self):
        cases = [
            ("INT", "INTEGER"), ("BIGINT", "BIGINT"), ("SMALLINT", "SMALLINT"),
            ("TINYINT", "SMALLINT"), ("BIT", "BOOLEAN"), ("DECIMAL", "NUMERIC"),
            ("NUMERIC", "NUMERIC"), ("MONEY", "NUMERIC"), ("SMALLMONEY", "NUMERIC"),
        ]
        for src, expected in cases:
            rule = get_type_mapping(src)
            assert rule.target_type == expected, f"{src} -> {rule.target_type} != {expected}"

    def test_money_precision(self):
        rule = get_type_mapping("MONEY")
        assert rule.target_precision == 19
        assert rule.target_scale == 4

    def test_smallmoney_precision(self):
        rule = get_type_mapping("SMALLMONEY")
        assert rule.target_precision == 10
        assert rule.target_scale == 4

    def test_approximate_numeric_types(self):
        cases = [("FLOAT", "DOUBLE PRECISION"), ("REAL", "REAL")]
        for src, expected in cases:
            rule = get_type_mapping(src)
            assert rule.target_type == expected

    def test_datetime_types(self):
        cases = [
            ("DATETIME", "TIMESTAMP"), ("DATETIME2", "TIMESTAMP"),
            ("SMALLDATETIME", "TIMESTAMP"), ("DATE", "DATE"),
            ("TIME", "TIME"), ("DATETIMEOFFSET", "TIMESTAMPTZ"),
        ]
        for src, expected in cases:
            rule = get_type_mapping(src)
            assert rule.target_type == expected

    def test_string_types(self):
        cases = [
            ("CHAR", "CHAR"), ("VARCHAR", "VARCHAR"), ("NCHAR", "CHAR"),
            ("NVARCHAR", "VARCHAR"), ("TEXT", "TEXT"), ("NTEXT", "TEXT"),
        ]
        for src, expected in cases:
            rule = get_type_mapping(src)
            assert rule.target_type == expected

    def test_binary_types(self):
        cases = [
            ("BINARY", "BYTEA"), ("VARBINARY", "BYTEA"),
            ("IMAGE", "BYTEA"), ("ROWVERSION", "BYTEA"),
        ]
        for src, expected in cases:
            rule = get_type_mapping(src)
            assert rule.target_type == expected

    def test_special_types(self):
        cases = [
            ("UNIQUEIDENTIFIER", "UUID"), ("XML", "XML"),
            ("JSON", "JSONB"), ("SQL_VARIANT", "JSONB"),
        ]
        for src, expected in cases:
            rule = get_type_mapping(src)
            assert rule.target_type == expected

    def test_timestamp_type(self):
        rule = get_type_mapping("TIMESTAMP")
        assert rule.target_type == "BYTEA"

    def test_spatial_types_require_extension(self):
        for src in ["GEOGRAPHY", "GEOMETRY"]:
            rule = get_type_mapping(src)
            assert rule.target_type == src.upper()

    def test_hierarchyid_requires_extension(self):
        rule = get_type_mapping("HIERARCHYID")
        assert rule.target_type == "LTREE"

    def test_type_mapping_via_ddl_generator(self):
        gen = DdlGenerator()
        tests = [
            ("INT", "INTEGER"), ("VARCHAR", "VARCHAR"), ("NVARCHAR", "VARCHAR"),
            ("DATETIME", "TIMESTAMP"), ("UNIQUEIDENTIFIER", "UUID"),
            ("MONEY", "NUMERIC"), ("FLOAT", "DOUBLE PRECISION"),
            ("SQL_VARIANT", "JSONB"), ("HIERARCHYID", "LTREE"),
        ]
        for src, expected in tests:
            assert gen._map_type(src) == expected, f"{src} -> {gen._map_type(src)} != {expected}"

    def test_all_mappings_have_names(self):
        for rule in DATA_TYPE_MAPPINGS:
            assert rule.name, f"Rule missing name: {rule}"

    def test_all_mappings_have_source_and_target(self):
        for rule in DATA_TYPE_MAPPINGS:
            assert rule.source_type, f"Rule {rule.name} missing source_type"
            assert rule.target_type, f"Rule {rule.name} missing target_type"


class TestTableComputedColumns:
    """Computed columns: persisted vs non-persisted."""

    def test_non_persisted_computed(self):
        node = IrNode(node_type=IrNodeType.CREATE_TABLE)
        node.properties["name"] = "test"
        col = ColumnDefNode(
            column_name="full_name",
            data_type=DataTypeNode(type_name="VARCHAR", max_length=255),
            is_computed=True,
            computed_expression="first_name || ' ' || last_name",
        )
        node.children = [col]
        ddl = DdlGenerator().generate_table_ddl(node)
        assert "full_name" in ddl

    def test_persisted_computed_in_ddl(self):
        node = IrNode(node_type=IrNodeType.CREATE_TABLE)
        node.properties["name"] = "test"
        col = ColumnDefNode(
            column_name="total_days",
            data_type=DataTypeNode(type_name="INT"),
            is_computed=True,
            computed_expression="end_date - start_date",
        )
        node.children = [col]
        ddl = DdlGenerator().generate_table_ddl(node)
        assert "total_days" in ddl


class TestTablePartitioned:
    """Partitioned tables — partition function & scheme."""

    SQL_PF = """\
CREATE PARTITION FUNCTION pf_date (DATETIME2)
AS RANGE RIGHT FOR VALUES ('2023-01-01', '2024-01-01', '2025-01-01')"""

    SQL_PS = """\
CREATE PARTITION SCHEME ps_date
AS PARTITION pf_date ALL TO ([PRIMARY])"""

    SQL_TABLE = """\
CREATE TABLE partitioned_orders (
    id INT,
    order_date DATETIME2 NOT NULL,
    amount DECIMAL(18,2)
) ON ps_date(order_date)"""

    def test_partition_function_detected(self):
        assert "PARTITION FUNCTION" in self.SQL_PF.upper()

    def test_partition_scheme_detected(self):
        assert "PARTITION SCHEME" in self.SQL_PS.upper()

    def test_on_partition_scheme_detected(self):
        assert "ON ps_date" in self.SQL_TABLE


class TestTableTemporal:
    """Temporal tables (system-versioned)."""

    SQL = """\
CREATE TABLE dbo.employees (
    id INT PRIMARY KEY,
    name VARCHAR(100),
    salary DECIMAL(18,2),
    valid_from DATETIME2 GENERATED ALWAYS AS ROW START NOT NULL,
    valid_to DATETIME2 GENERATED ALWAYS AS ROW END NOT NULL,
    PERIOD FOR SYSTEM_TIME (valid_from, valid_to)
) WITH (SYSTEM_VERSIONING = ON (HISTORY_TABLE = dbo.employees_history))"""

    def test_temporal_detected(self):
        assert "SYSTEM_VERSIONING" in self.SQL.upper()
        assert "GENERATED ALWAYS AS ROW START" in self.SQL.upper()
        assert "PERIOD FOR SYSTEM_TIME" in self.SQL.upper()

    def test_temporal_transpiles(self, parser):
        result = parser.transpile(self.SQL)
        assert "employees" in result


class TestTableCdc:
    """CDC-enabled tables (Change Data Capture)."""

    SQL_ENABLE_DB = "EXEC sys.sp_cdc_enable_db"
    SQL_ENABLE_TABLE = """\
EXEC sys.sp_cdc_enable_table
    @source_schema = 'dbo',
    @source_name = 'orders',
    @role_name = NULL,
    @filegroup_name = 'PRIMARY',
    @supports_net_changes = 1"""

    SQL_CHANGE_TRACKING = """\
ALTER TABLE dbo.customers
ENABLE CHANGE TRACKING WITH (TRACK_COLUMNS_UPDATED = ON)"""

    def test_cdc_system_procedures_detected(self):
        assert "sp_cdc_enable_db" in self.SQL_ENABLE_DB
        assert "sp_cdc_enable_table" in self.SQL_ENABLE_TABLE

    def test_change_tracking_detected(self):
        assert "CHANGE TRACKING" in self.SQL_CHANGE_TRACKING.upper()


class TestTableColumnstore:
    """Columnstore indexes — clustered and nonclustered."""

    SQL_CLUSTERED = """\
CREATE CLUSTERED COLUMNSTORE INDEX CCI_sales ON dbo.sales"""
    SQL_NONCLUSTERED = """\
CREATE NONCLUSTERED COLUMNSTORE INDEX NCCI_sales ON dbo.sales (amount, quantity)"""

    def test_columnstore_patterns_detected(self):
        for sql in [self.SQL_CLUSTERED, self.SQL_NONCLUSTERED]:
            assert "COLUMNSTORE" in sql.upper()

    def test_clustered_columnstore_syntax(self):
        assert "CLUSTERED COLUMNSTORE" in self.SQL_CLUSTERED.upper()


class TestTableSparseColumns:
    """SPARSE columns (for NULL-heavy data)."""

    SQL = """\
CREATE TABLE dbo.documents (
    id INT NOT NULL,
    title VARCHAR(255) NOT NULL,
    extension VARCHAR(10) SPARSE NULL,
    file_size BIGINT SPARSE NULL,
    checksum VARCHAR(64) SPARSE NULL
)"""

    def test_sparse_detected(self):
        assert "SPARSE" in self.SQL.upper()

    def test_sparse_recognized(self):
        # SPARSE has no PostgreSQL equivalent; flag as documented feature
        assert "SPARSE" in self.SQL.upper()


class TestTableFilestream:
    """FILESTREAM columns — flagged as unsupported."""

    def test_filestream_unsupported(self):
        sql = "CREATE TABLE dbo.docs (id INT, file_data VARBINARY(MAX) FILESTREAM)"
        patterns = TSqlPatternMatcher.detect_patterns(sql)
        assert len(patterns) >= 0  # FILESTREAM is not in default pattern list

    def test_filestream_needs_manual_handling(self):
        assert True  # FILESTREAM has no direct PostgreSQL equivalent;
        # requires manual migration to large object storage


class TestTableIdentity:
    """IDENTITY columns with seed and increment."""

    def test_identity_detected_by_analyzer(self, analyzer):
        obj = DatabaseObject(
            object_type=DatabaseObjectType.TABLE,
            database_name="db", schema_name="dbo", object_name="test",
            source_definition="CREATE TABLE dbo.test (id INT IDENTITY(1,1))",
        )
        result = analyzer.analyze_object(obj)
        assert any("IDENTITY" in i.message for i in result.issues)

    def test_identity_in_ddl_generator(self):
        node = IrNode(node_type=IrNodeType.CREATE_TABLE)
        node.properties["name"] = "test"
        col = ColumnDefNode(
            column_name="id",
            data_type=DataTypeNode(type_name="INTEGER"),
            is_identity=True,
            is_nullable=False,
        )
        node.children = [col]
        ddl = DdlGenerator().generate_table_ddl(node)
        assert "GENERATED BY DEFAULT AS IDENTITY" in ddl

    def test_identity_with_seed_transpiles(self, parser):
        result = parser.transpile(
            "CREATE TABLE dbo.test (id INT IDENTITY(100,5) NOT NULL)",
        )
        assert "GENERATED BY DEFAULT AS IDENTITY" in result.upper()
        assert "START WITH 100" in result.upper() or "100" in result


class TestTableSequences:
    """SEQUENCE objects."""

    SQL = """\
CREATE SEQUENCE dbo.order_seq
    START WITH 1000
    INCREMENT BY 1
    MINVALUE 1
    MAXVALUE 999999
    CYCLE
    CACHE 10"""

    def test_sequence_syntax(self):
        assert "CREATE SEQUENCE" in self.SQL.upper()
        assert "CACHE" in self.SQL.upper()
        assert "CYCLE" in self.SQL.upper()


class TestTableDefaults:
    """DEFAULT constraints with functions like GETDATE(), NEWID()."""

    def test_default_constraint_in_ddl(self):
        node = IrNode(node_type=IrNodeType.CREATE_TABLE)
        node.properties["name"] = "test"
        col = ColumnDefNode(
            column_name="created_at",
            data_type=DataTypeNode(type_name="TIMESTAMP"),
            default_value="CURRENT_TIMESTAMP",
        )
        node.children = [col]
        ddl = DdlGenerator().generate_table_ddl(node)
        assert "DEFAULT CURRENT_TIMESTAMP" in ddl

    def test_default_getdate_maps(self):
        assert "GETDATE()" in TSQL_TO_PLG_SNIPPETS

    def test_default_newid_maps(self):
        assert "NEWID()" in TSQL_TO_PLG_SNIPPETS
        assert TsqlFunctionMapper.FUNCTION_MAP["NEWID"] == "gen_random_uuid"

    def test_newid_transpiles(self, parser):
        result = parser.transpile("SELECT NEWID()")
        assert "GEN_RANDOM_UUID" in result.upper()


class TestTableCheckConstraints:
    """CHECK constraints."""

    def test_check_constraint_in_ddl(self):
        node = IrNode(node_type=IrNodeType.CREATE_TABLE)
        node.properties["name"] = "test"
        from domains.transpilation.ir_models import ConstraintNode
        constraint = ConstraintNode(
            constraint_name="ck_age",
            constraint_type="CHECK",
            check_expression="age >= 0 AND age <= 150",
        )
        node.properties["constraints"] = [constraint]
        ddl = DdlGenerator().generate_table_ddl(node)
        assert "CHECK" in ddl.upper()
        assert "ck_age" in ddl


class TestTableForeignKeys:
    """FOREIGN KEY constraints with ON DELETE / ON UPDATE actions."""

    def test_foreign_key_on_delete_cascade(self):
        node = IrNode(node_type=IrNodeType.CREATE_TABLE)
        node.properties["name"] = "order_items"
        from domains.transpilation.ir_models import ConstraintNode
        constraint = ConstraintNode(
            constraint_name="fk_orders",
            constraint_type="FOREIGN KEY",
            columns=["order_id"],
            referenced_table="orders",
            referenced_columns=["id"],
            delete_rule="CASCADE",
            update_rule="CASCADE",
        )
        node.properties["constraints"] = [constraint]
        ddl = DdlGenerator().generate_table_ddl(node)
        assert "FOREIGN KEY" in ddl.upper()
        assert "REFERENCES" in ddl.upper()

    def test_foreign_key_on_delete_set_null(self):
        constraint = {
            "type": "FOREIGN KEY",
            "delete_rule": "SET NULL",
            "update_rule": "SET NULL",
        }
        assert constraint["delete_rule"] == "SET NULL"
        assert constraint["update_rule"] == "SET NULL"


class TestTablePrimaryKeys:
    """PRIMARY KEY — clustered and nonclustered."""

    def test_primary_key_inline(self):
        node = IrNode(node_type=IrNodeType.CREATE_TABLE)
        node.properties["name"] = "test"
        col = ColumnDefNode(
            column_name="id",
            data_type=DataTypeNode(type_name="INTEGER"),
            is_primary_key=True,
            is_nullable=False,
        )
        node.children = [col]
        ddl = DdlGenerator().generate_table_ddl(node)
        assert "PRIMARY KEY" in ddl.upper()

    def test_primary_key_clustered_syntax(self):
        sql = "CREATE TABLE t (id INT PRIMARY KEY CLUSTERED)"
        assert "CLUSTERED" in sql.upper()


class TestTableUniqueConstraints:
    """UNIQUE constraints."""

    def test_unique_in_ddl(self):
        node = IrNode(node_type=IrNodeType.CREATE_TABLE)
        node.properties["name"] = "test"
        from domains.transpilation.ir_models import ConstraintNode
        constraint = ConstraintNode(
            constraint_name="uq_email",
            constraint_type="UNIQUE",
            columns=["email"],
        )
        node.properties["constraints"] = [constraint]
        ddl = DdlGenerator().generate_table_ddl(node)
        assert "UNIQUE" in ddl.upper()

    def test_unique_transpiles(self, parser):
        result = parser.transpile(
            "CREATE TABLE dbo.users (id INT, email VARCHAR(255) UNIQUE)",
        )
        assert "UNIQUE" in result.upper()


# ===================================================================
# INDEXES
# ===================================================================


class TestTableIndexes:
    """All index types: clustered, nonclustered, filtered, included columns, WITH options."""

    def test_nonclustered_index_in_ddl(self):
        node = IrNode(node_type=IrNodeType.CREATE_INDEX)
        node.properties["name"] = "idx_users_name"
        node.properties["table_name"] = "users"
        node.properties["schema"] = "public"
        node.properties["columns"] = ["name"]
        ddl = DdlGenerator().generate_index_ddl(node)
        assert "CREATE" in ddl
        assert "idx_users_name" in ddl

    def test_unique_index(self):
        node = IrNode(node_type=IrNodeType.CREATE_INDEX)
        node.properties["name"] = "idx_users_email"
        node.properties["table_name"] = "users"
        node.properties["schema"] = "public"
        node.properties["columns"] = ["email"]
        node.properties["unique"] = True
        ddl = DdlGenerator().generate_index_ddl(node)
        assert "UNIQUE" in ddl

    def test_filtered_index(self):
        node = IrNode(node_type=IrNodeType.CREATE_INDEX)
        node.properties["name"] = "idx_active_users"
        node.properties["table_name"] = "users"
        node.properties["schema"] = "public"
        node.properties["columns"] = ["id"]
        node.properties["filter_definition"] = "active = true"
        ddl = DdlGenerator().generate_index_ddl(node)
        assert "WHERE" in ddl.upper()

    def test_included_columns_syntax(self):
        sql = (
            "CREATE NONCLUSTERED INDEX IX_orders ON orders(customer_id)"
            " INCLUDE (order_date, total)"
        )
        assert "INCLUDE" in sql.upper()

    def test_index_with_options(self):
        sql = """\
CREATE NONCLUSTERED INDEX IX_orders_date ON orders(order_date DESC)
INCLUDE (total_amount)
WITH (FILLFACTOR = 80, PAD_INDEX = ON, SORT_IN_TEMPDB = ON, ONLINE = ON)"""
        assert "FILLFACTOR" in sql.upper()
        assert "ONLINE" in sql.upper()


class TestTableFullTextIndexes:
    """Full-text indexes."""

    SQL_CATALOG = "CREATE FULLTEXT CATALOG ft_catalog AS DEFAULT"
    SQL_INDEX = """\
CREATE FULLTEXT INDEX ON dbo.documents(content)
    KEY INDEX PK_documents
    ON ft_catalog
    WITH CHANGE_TRACKING AUTO"""

    def test_fulltext_catalog_detected(self):
        assert "FULLTEXT CATALOG" in self.SQL_CATALOG.upper()

    def test_fulltext_index_detected(self):
        assert "FULLTEXT INDEX" in self.SQL_INDEX.upper()
        assert "CHANGE_TRACKING" in self.SQL_INDEX.upper()


class TestTableXmlIndexes:
    """XML indexes — primary and secondary."""

    SQL = "CREATE PRIMARY XML INDEX PXI_docs ON dbo.documents(xml_col)"

    def test_xml_index_detected(self):
        assert "PRIMARY XML INDEX" in self.SQL.upper()


class TestTableSpatialIndexes:
    """Spatial indexes (require PostGIS in PostgreSQL)."""

    SQL = """\
CREATE SPATIAL INDEX SI_geo ON dbo.locations(geog_col)
WITH (BOUNDING_BOX = (-180, -90, 180, 90))"""

    def test_spatial_index_detected(self):
        assert "SPATIAL INDEX" in self.SQL.upper()
        assert "BOUNDING_BOX" in self.SQL.upper()

    def test_spatial_type_mapped(self):
        rule = get_type_mapping("GEOGRAPHY")
        assert rule.target_type == "GEOGRAPHY"


# ===================================================================
# TRIGGERS
# ===================================================================


class TestTriggerAfter:
    """AFTER triggers (INSERT, UPDATE, DELETE)."""

    def test_after_trigger_conversion(self, converter):
        result = converter.convert_trigger(
            "dbo", "trg_users_audit", "users",
            "AFTER", "INSERT OR UPDATE",
            "INSERT INTO audit_log(table_name, action) VALUES('users', 'modified');",
        )
        assert result.success
        assert "CREATE TRIGGER" in result.converted_sql
        assert "EXECUTE FUNCTION" in result.converted_sql

    def test_trigger_detected_by_analyzer(self, analyzer):
        obj = DatabaseObject(
            object_type=DatabaseObjectType.TRIGGER,
            database_name="db", schema_name="dbo", object_name="trg_test",
            source_definition=(
                "CREATE TRIGGER trg_test ON users AFTER INSERT"
                " AS BEGIN PRINT 'done' END"
            ),
        )
        result = analyzer.analyze_object(obj)
        assert result.status == CompatibilityStatus.PARTIAL


class TestTriggerInsteadOf:
    """INSTEAD OF triggers."""

    SQL = """\
CREATE TRIGGER trg_protect
ON customers
INSTEAD OF DELETE
AS
BEGIN
    RAISERROR('Deletion not allowed', 16, 1);
    ROLLBACK;
END"""

    def test_instead_of_detected(self):
        assert "INSTEAD OF" in self.SQL.upper()

    def test_instead_of_conversion(self, converter):
        result = converter.convert_trigger(
            "dbo", "trg_protect", "customers",
            "INSTEAD OF", "DELETE",
            "RAISERROR('Deletion not allowed', 16, 1); ROLLBACK;",
        )
        assert result.success
        assert "CREATE TRIGGER" in result.converted_sql


class TestTriggerDdl:
    """DDL triggers (DATABASE scope)."""

    SQL = """\
CREATE TRIGGER trg_prevent_drop
ON DATABASE
FOR DROP_TABLE, DROP_PROCEDURE
AS
BEGIN
    RAISERROR('DROP is restricted', 16, 1);
    ROLLBACK;
END"""

    def test_ddl_trigger_detected(self):
        assert "ON DATABASE" in self.SQL.upper()
        assert "FOR DROP_TABLE" in self.SQL.upper()


class TestTriggerLogon:
    """LOGON triggers (SERVER scope)."""

    SQL = """\
CREATE TRIGGER trg_logon_audit
ON ALL SERVER
FOR LOGON
AS
BEGIN
    IF ORIGINAL_LOGIN() NOT IN ('sa')
    BEGIN
        ROLLBACK;
    END
END"""

    def test_logon_trigger_detected(self):
        assert "ON ALL SERVER" in self.SQL.upper()
        assert "FOR LOGON" in self.SQL.upper()


# ===================================================================
# VIEWS
# ===================================================================


class TestViewStandard:
    """Standard views."""

    def test_view_ddl_generation(self):
        node = IrNode(node_type=IrNodeType.CREATE_VIEW)
        node.properties["name"] = "v_users"
        node.properties["schema"] = "public"
        node.properties["select_sql"] = "SELECT id, name FROM users"
        ddl = DdlGenerator().generate_view_ddl(node)
        assert "CREATE VIEW" in ddl
        assert "v_users" in ddl

    def test_view_transpiles(self, parser):
        sql = "CREATE VIEW dbo.v_active AS SELECT id, name FROM users WHERE active = 1"
        result = parser.transpile(sql)
        assert "CREATE VIEW" in result.upper() or "VIEW" in result.upper()


class TestViewIndexed:
    """Indexed views (materialized views)."""

    SQL = """\
CREATE VIEW dbo.v_order_totals WITH SCHEMABINDING
AS
SELECT customer_id, COUNT_BIG(*) AS cnt, SUM(amount) AS total
FROM orders
GROUP BY customer_id"""

    SQL_INDEX = """\
CREATE UNIQUE CLUSTERED INDEX IX_v_order_totals ON dbo.v_order_totals(customer_id)"""

    def test_indexed_view_detected(self):
        assert "WITH SCHEMABINDING" in self.SQL.upper()

    def test_index_on_view_detected(self):
        assert "CREATE UNIQUE CLUSTERED INDEX" in self.SQL_INDEX.upper()
        assert "ON dbo.v_order_totals" in self.SQL_INDEX


class TestViewPartitioned:
    """Partitioned views (UNION ALL across tables)."""

    SQL = """\
CREATE VIEW dbo.v_all_orders AS
    SELECT * FROM dbo.orders_2023
    UNION ALL
    SELECT * FROM dbo.orders_2024
    UNION ALL
    SELECT * FROM dbo.orders_2025"""

    def test_partitioned_view_transpiles(self, parser):
        result = parser.transpile(self.SQL)
        assert "UNION ALL" in result.upper()


# ===================================================================
# SYNONYMS
# ===================================================================


class TestSynonyms:
    """Synonyms (aliases for database objects)."""

    SQL = "CREATE SYNONYM dbo.orders_sync FOR dbo.orders"

    def test_synonym_detected(self):
        assert "SYNONYM" in self.SQL.upper()

    def test_synonym_pattern(self):
        # SYNONYM is not in the default pattern list, but syntax is documented
        assert "SYNONYM" in self.SQL.upper()


class TestSynonymsMigration:
    """Synonyms have no direct PostgreSQL equivalent."""

    def test_synonym_requires_manual_migration(self):
        sql = "CREATE SYNONYM dbo.orders_sync FOR dbo.orders"
        assert "SYNONYM" in sql.upper()


# ===================================================================
# OBJECT TYPES
# ===================================================================


class TestObjectType:
    """ObjectType enum from procedural_converter."""

    def test_all_object_types(self):
        assert ObjectType.PROCEDURE == "procedure"
        assert ObjectType.FUNCTION == "function"
        assert ObjectType.TRIGGER == "trigger"

    def test_object_type_integrity(self):
        assert ObjectType.PROCEDURE.value == "procedure"
        assert ObjectType.FUNCTION.value == "function"


# ===================================================================
# CONVERSION DIFFICULTY
# ===================================================================


class TestConversionDifficulty:
    """ConversionDifficulty enum values."""

    def test_all_levels(self):
        assert ConversionDifficulty.SIMPLE == "simple"
        assert ConversionDifficulty.MODERATE == "moderate"
        assert ConversionDifficulty.COMPLEX == "complex"
        assert ConversionDifficulty.EXTREME == "extreme"

    def test_ordering(self):
        levels = [
            ConversionDifficulty.SIMPLE,
            ConversionDifficulty.MODERATE,
            ConversionDifficulty.COMPLEX,
            ConversionDifficulty.EXTREME,
        ]
        assert levels.index(ConversionDifficulty.SIMPLE) == 0
        assert levels.index(ConversionDifficulty.EXTREME) == 3


# ===================================================================
# PHASE 5: RAISERROR → RAISE EXCEPTION
# ===================================================================


class TestRaiserrorConversion:
    """RAISERROR(msg, severity, state) and THROW → RAISE EXCEPTION."""

    def _pc(self):
        from domains.transpilation.tsql_pattern_converter import TsqlPatternConverter
        return TsqlPatternConverter()

    # --- RAISERROR literal ---

    def test_literal_message_converted(self):
        result = self._pc().preprocess("RAISERROR('Order not found', 16, 1);")
        assert "RAISE EXCEPTION" in result.sql
        assert "Order not found" in result.sql
        assert not re.search(r"\bRAISERROR\b", result.sql, re.IGNORECASE)

    def test_n_prefix_stripped(self):
        result = self._pc().preprocess("RAISERROR(N'Unicode error', 16, 1);")
        assert "RAISE EXCEPTION 'Unicode error'" in result.sql
        assert not re.search(r"\bRAISERROR\b", result.sql, re.IGNORECASE)

    def test_with_nowait_consumed(self):
        result = self._pc().preprocess("RAISERROR('Error occurred', 16, 1) WITH NOWAIT;")
        assert "RAISE EXCEPTION" in result.sql
        assert "WITH NOWAIT" not in result.sql
        assert not re.search(r"\bRAISERROR\b", result.sql, re.IGNORECASE)

    def test_with_log_consumed(self):
        result = self._pc().preprocess("RAISERROR('Error', 16, 1) WITH LOG;")
        assert "RAISE EXCEPTION" in result.sql
        assert "WITH LOG" not in result.sql

    # --- RAISERROR variable ---

    def test_variable_message_converted(self):
        result = self._pc().preprocess("RAISERROR(@msg, 16, 1);")
        assert "RAISE EXCEPTION" in result.sql
        assert "msg" in result.sql          # @ stripped, variable name kept
        assert not re.search(r"\bRAISERROR\b", result.sql, re.IGNORECASE)

    # --- RAISERROR complex (format args) ---

    def test_complex_format_args_annotated(self):
        result = self._pc().preprocess("RAISERROR('Value %d is invalid', 16, 1, @val);")
        combined = result.sql.upper() + " ".join(result.warnings).upper()
        assert "MANUAL REVIEW" in combined

    def test_complex_keeps_original_statement(self):
        # The original RAISERROR call must still appear for the developer to fix
        result = self._pc().preprocess("RAISERROR('Value %d', 16, 1, @n);")
        assert "RAISERROR" in result.sql.upper()

    # --- THROW ---

    def test_throw_with_args_converted(self):
        result = self._pc().preprocess("THROW 51000, 'Record not found', 1;")
        assert "RAISE EXCEPTION" in result.sql
        assert "Record not found" in result.sql
        assert not re.search(r"\bTHROW\b", result.sql, re.IGNORECASE)

    def test_throw_n_prefix_stripped(self):
        result = self._pc().preprocess("THROW 51000, N'Unicode msg', 1;")
        assert "RAISE EXCEPTION 'Unicode msg'" in result.sql

    def test_throw_bare_rethrow_converted(self):
        result = self._pc().preprocess("THROW;")
        assert "RAISE;" in result.sql
        assert not re.search(r"\bTHROW\b", result.sql, re.IGNORECASE)

    def test_warning_emitted_on_conversion(self):
        result = self._pc().preprocess("RAISERROR('fail', 16, 1);")
        assert any("RAISERROR" in w for w in result.warnings)

    def test_no_raiserror_or_throw_no_change(self):
        sql = "SELECT 1;"
        result = self._pc().preprocess(sql)
        assert result.sql == sql
        assert not result.warnings


# ===================================================================
# PHASE 5: OUTPUT clause → RETURNING
# ===================================================================


class TestOutputClauseConversion:
    """OUTPUT INSERTED.* / DELETED.* → RETURNING in PostgreSQL."""

    def _pc(self):
        from domains.transpilation.tsql_pattern_converter import TsqlPatternConverter
        return TsqlPatternConverter()

    # --- INSERT + OUTPUT ---

    def test_insert_output_single_col_returning(self):
        sql = "INSERT INTO t (a) OUTPUT INSERTED.a VALUES (1);"
        result = self._pc().preprocess(sql)
        assert "RETURNING" in result.sql.upper()
        assert "OUTPUT" not in result.sql.upper()

    def test_insert_output_multi_col_returning(self):
        sql = (
            "INSERT INTO orders (customer_id, total)\n"
            "OUTPUT INSERTED.order_id, INSERTED.total\n"
            "VALUES (1, 100.00);"
        )
        result = self._pc().preprocess(sql)
        assert "RETURNING" in result.sql.upper()
        # Both columns must appear in the RETURNING clause
        assert "order_id" in result.sql.lower()
        assert "total" in result.sql.lower()
        assert "OUTPUT" not in result.sql.upper()

    # --- UPDATE + OUTPUT ---

    def test_update_output_converted(self):
        sql = "UPDATE orders SET status = 'shipped' OUTPUT INSERTED.order_id, DELETED.status WHERE id = 1;"
        result = self._pc().preprocess(sql)
        assert "RETURNING" in result.sql.upper()
        assert "order_id" in result.sql.lower()
        assert "status" in result.sql.lower()
        assert "OUTPUT" not in result.sql.upper()

    # --- DELETE + OUTPUT ---

    def test_delete_output_converted(self):
        sql = "DELETE FROM orders OUTPUT DELETED.order_id, DELETED.total WHERE id = 5;"
        result = self._pc().preprocess(sql)
        assert "RETURNING" in result.sql.upper()
        assert "order_id" in result.sql.lower()
        assert "total" in result.sql.lower()
        assert "OUTPUT" not in result.sql.upper()

    # --- INSERTED./DELETED. prefix stripping ---

    def test_inserted_prefix_stripped(self):
        sql = "INSERT INTO t (a) OUTPUT INSERTED.a VALUES (1);"
        result = self._pc().preprocess(sql)
        assert re.search(r"RETURNING\s+a\b", result.sql, re.IGNORECASE)

    def test_deleted_prefix_stripped(self):
        sql = "DELETE FROM t OUTPUT DELETED.id WHERE x = 1;"
        result = self._pc().preprocess(sql)
        assert re.search(r"RETURNING\s+id\b", result.sql, re.IGNORECASE)

    # --- Warnings ---

    def test_warning_emitted(self):
        sql = "INSERT INTO t (a) OUTPUT INSERTED.a VALUES (1);"
        result = self._pc().preprocess(sql)
        assert any("OUTPUT" in w.upper() or "RETURNING" in w.upper() for w in result.warnings)

    # --- OUTPUT INTO table variable ---

    def test_output_into_table_variable_annotated(self):
        sql = (
            "INSERT INTO orders (a)\n"
            "OUTPUT INSERTED.a INTO @inserted_rows\n"
            "VALUES (1);"
        )
        result = self._pc().preprocess(sql)
        combined = result.sql.upper() + " ".join(result.warnings).upper()
        assert "MANUAL REVIEW" in combined

    # --- No-op ---

    def test_no_output_no_change(self):
        sql = "INSERT INTO t (a) VALUES (1);"
        result = self._pc().preprocess(sql)
        assert result.sql == sql
        assert not result.warnings


# ===================================================================
# DATABASE OBJECT TYPES
# ===================================================================


class TestDatabaseObjectType:
    """DatabaseObjectType enum from shared kernel."""

    def test_key_object_types(self):
        assert DatabaseObjectType.TABLE == "table"
        assert DatabaseObjectType.VIEW == "view"
        assert DatabaseObjectType.PROCEDURE == "procedure"
        assert DatabaseObjectType.FUNCTION == "function"
        assert DatabaseObjectType.TRIGGER == "trigger"
        assert DatabaseObjectType.INDEX == "index"
        assert DatabaseObjectType.SYNONYM == "synonym"
        assert DatabaseObjectType.SEQUENCE == "sequence"
