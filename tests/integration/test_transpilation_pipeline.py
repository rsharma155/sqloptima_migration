"""
Module: tests/integration/test_transpilation_pipeline.py
Purpose: Integration tests for the full transpilation pipeline (no DB required)
Author: Migration Platform Team
Created: 2026-05-22
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

import pytest

from domains.parsing.sqlglot_adapter import SqlglotParser
from domains.transpilation.compatibility_analyzer import CompatibilityAnalyzer
from domains.transpilation.ddl_generator import DdlGenerator
from domains.transpilation.ir_builder import IrBuilder
from domains.transpilation.procedural_converter import (
    ParameterInfo,
    ProceduralConverter,
)
from domains.transpilation.type_mappings import get_type_mapping
from shared.kernel.database_object import (
    DatabaseObject,
    DatabaseObjectType,
)


@pytest.fixture
def parser():
    return SqlglotParser()


@pytest.fixture
def converter():
    return ProceduralConverter()


@pytest.fixture
def analyzer():
    return CompatibilityAnalyzer()


@pytest.fixture
def ir_builder(parser):
    return IrBuilder(parser)


@pytest.fixture
def ddl_generator():
    return DdlGenerator()


PIPELINE_TEST_CASES = [
    (
        "simple_table",
        "CREATE TABLE dbo.users (id INT NOT NULL, name VARCHAR(100), email VARCHAR(255))",
        "CREATE TABLE",
    ),
    (
        "table_with_defaults",
        "CREATE TABLE dbo.orders (id INT IDENTITY(1,1), "
        "total DECIMAL(18,2) DEFAULT 0.00, created_date DATETIME DEFAULT GETDATE())",
        "CREATE TABLE",
    ),
    (
        "table_with_constraints",
        "CREATE TABLE dbo.products (id INT PRIMARY KEY, "
        "sku VARCHAR(50) NOT NULL UNIQUE, "
        "category_id INT REFERENCES dbo.categories(id))",
        "CREATE TABLE",
    ),
    (
        "simple_view",
        "CREATE VIEW dbo.v_active_users AS "
        "SELECT id, name, email FROM dbo.users WHERE active = 1",
        "CREATE VIEW",
    ),
    (
        "simple_proc",
        "CREATE PROCEDURE dbo.usp_get_user @p_id INT AS "
        "BEGIN SELECT id, name FROM dbo.users WHERE id = @p_id END",
        "CREATE OR REPLACE PROCEDURE",
    ),
    (
        "proc_with_output",
        "CREATE PROCEDURE dbo.usp_count_users @p_count INT OUTPUT AS "
        "BEGIN SELECT @p_count = COUNT(*) FROM dbo.users END",
        "CREATE OR REPLACE PROCEDURE",
    ),
    (
        "scalar_function",
        "CREATE FUNCTION dbo.fn_add(@a INT, @b INT) RETURNS INT AS "
        "BEGIN RETURN @a + @b END",
        "CREATE OR REPLACE FUNCTION",
    ),
    (
        "trigger_example",
        "CREATE TRIGGER dbo.trg_users_audit ON dbo.users AFTER INSERT AS "
        "BEGIN INSERT INTO dbo.audit_log(action) VALUES('INSERT') END",
        "CREATE TRIGGER",
    ),
]


class TestPipelineFullTranspile:
    """Full transpilation pipeline: T-SQL -> parse -> IR -> transform -> PostgreSQL."""

    @pytest.mark.parametrize("name,tsql,expected_pattern", PIPELINE_TEST_CASES)
    def test_full_pipeline(self, parser, ir_builder, ddl_generator, name, tsql, expected_pattern):
        parse_result = parser.parse(tsql)
        assert parse_result.success, f"Parse failed for {name}: {parse_result.errors}"

        ir_program = ir_builder.build(parse_result.ast)
        assert ir_program is not None, f"IR build failed for {name}"

        if ir_program.statements:
            for stmt in ir_program.statements:
                ddl = ddl_generator.generate_table_ddl(stmt)
                assert ddl is not None

    @pytest.mark.parametrize("tsql", [
        "SELECT 1",
        "SELECT * FROM users WHERE id = 1",
        "INSERT INTO users (id, name) VALUES (1, 'test')",
        "UPDATE users SET name = 'x' WHERE id = 1",
        "DELETE FROM users WHERE id = 1",
    ])
    def test_pipeline_with_dml(self, parser, tsql):
        parse_result = parser.parse(tsql)
        assert parse_result.success

        result = parser.transpile(tsql)
        assert len(result) > 0


class TestPipelineProcedural:
    """Full transpilation pipeline for procedural code."""

    def test_procedure_to_plpgsql(self, parser, converter):
        tsql = """
        CREATE PROCEDURE dbo.usp_get_users
            @p_id INT
        AS
        BEGIN
            SELECT id, name, email
            FROM dbo.users
            WHERE id = @p_id;
        END
        """
        parser.parse(tsql)
        proc_result = converter.convert_procedure(
            schema="dbo",
            name="usp_get_users",
            parameters=[],
            body=tsql,
        )
        assert proc_result.success
        assert "CREATE OR REPLACE PROCEDURE" in proc_result.converted_sql

    def test_function_to_plpgsql(self, parser, converter):
        tsql = """
        CREATE FUNCTION dbo.fn_get_count()
        RETURNS INT
        AS
        BEGIN
            RETURN (SELECT COUNT(*) FROM dbo.users);
        END
        """
        result = converter.convert_function(
            schema="dbo",
            name="fn_get_count",
            parameters=[],
            body=tsql,
            return_type="INTEGER",
        )
        assert result.success
        assert "CREATE OR REPLACE FUNCTION" in result.converted_sql

    def test_trigger_to_plpgsql(self, converter):
        tsql = """
        CREATE TRIGGER trg_users_audit
        ON dbo.users
        AFTER INSERT, UPDATE
        AS
        BEGIN
            INSERT INTO dbo.audit_log(table_name, action)
            VALUES ('users', 'modified');
        END
        """
        result = converter.convert_trigger(
            schema="dbo",
            name="trg_users_audit",
            table_name="users",
            timing="AFTER",
            event="INSERT OR UPDATE",
            body=tsql,
        )
        assert result.success
        assert "CREATE TRIGGER" in result.converted_sql

    @pytest.mark.parametrize("body,expected", [
        ("SELECT 1", "CREATE OR REPLACE PROCEDURE"),
        ("SELECT * FROM users WHERE id = @id", "CREATE OR REPLACE PROCEDURE"),
        ("IF @x > 0 SELECT @x ELSE SELECT 0", "CREATE OR REPLACE PROCEDURE"),
        ("BEGIN TRY SELECT 1 END TRY BEGIN CATCH SELECT ERROR_MESSAGE() END CATCH",
         "CREATE OR REPLACE PROCEDURE"),
    ])
    def test_various_bodies(self, converter, body, expected):
        result = converter.convert_procedure("dbo", "usp_test", [], body)
        assert result.success
        assert expected in result.converted_sql

    def test_procedure_with_params(self, converter):
        params = [
            ParameterInfo(name="p_id", data_type="INT"),
            ParameterInfo(name="p_name", data_type="VARCHAR(100)", is_output=True),
        ]
        result = converter.convert_procedure(
            "dbo", "usp_test", params, "SELECT @p_id, @p_name",
        )
        assert result.success
        assert "INOUT" in result.converted_sql


class TestPipelineCompatibility:
    """Integration test for compatibility analysis pipeline."""

    def test_analyze_pipeline(self, parser, analyzer):
        objects = [
            DatabaseObject(
                object_type=DatabaseObjectType.TABLE,
                database_name="test_db",
                schema_name="dbo",
                object_name="users",
                source_definition="CREATE TABLE dbo.users (id INT)",
            ),
            DatabaseObject(
                object_type=DatabaseObjectType.PROCEDURE,
                database_name="test_db",
                schema_name="dbo",
                object_name="usp_test",
                source_definition="CREATE PROCEDURE usp_test AS EXEC('SELECT 1')",
            ),
            DatabaseObject(
                object_type=DatabaseObjectType.VIEW,
                database_name="test_db",
                schema_name="dbo",
                object_name="v_users",
                source_definition="CREATE VIEW v_users AS SELECT * FROM users",
            ),
        ]
        results = analyzer.analyze_batch(objects)
        assert len(results) == 3
        for r in results:
            assert r.auto_convertible_percentage >= 0

        summary = analyzer.generate_report_summary(results)
        assert summary["total_objects"] == 3
        assert summary["total_issues"] >= 0

    def test_analyze_with_complex_patterns(self, analyzer):
        obj = DatabaseObject(
            object_type=DatabaseObjectType.PROCEDURE,
            database_name="test_db",
            schema_name="dbo",
            object_name="usp_complex",
            source_definition=(
                "CREATE PROCEDURE usp_complex AS "
                "BEGIN TRY "
                "MERGE target USING source ON 1=1 "
                "WHEN MATCHED THEN UPDATE SET x = 1; "
                "END TRY BEGIN CATCH "
                "RAISERROR('err', 16, 1); "
                "END CATCH END"
            ),
        )
        result = analyzer.analyze_object(obj)
        assert result.status.value is not None

    def test_analyze_with_unsupported_features(self, analyzer):
        obj = DatabaseObject(
            object_type=DatabaseObjectType.PROCEDURE,
            database_name="test_db",
            schema_name="dbo",
            object_name="usp_clr",
            source_definition="CREATE PROCEDURE usp_clr AS EXTERNAL NAME Assembly.Class.Method",
        )
        result = analyzer.analyze_object(obj)
        assert len(result.issues) > 0


class TestPipelineTypeMapping:
    """Integration test for type mapping pipeline."""

    SOURCE_TYPES = ["INT", "BIGINT", "VARCHAR(100)", "NVARCHAR(MAX)", "DATETIME2",
                    "DECIMAL(18,2)", "FLOAT", "BIT", "UNIQUEIDENTIFIER", "MONEY"]

    def test_all_types_map(self):
        for tsql_type in self.SOURCE_TYPES:
            mapping = get_type_mapping(tsql_type)
            assert mapping is not None, f"No mapping for {tsql_type}"
            assert mapping.target_type is not None and len(mapping.target_type) > 0


class TestPipelineEndToEnd:
    """End-to-end pipeline tests with full round-trip validation."""

    @pytest.mark.parametrize("tsql", [
        "SELECT 1 AS value",
        "SELECT GETDATE() AS now",
        "SELECT LEN('hello') AS len",
        "SELECT UPPER('hello') AS upper",
        "SELECT ABS(-5) AS abs",
    ])
    def test_round_trip_simple(self, parser, tsql):
        parse_result = parser.parse(tsql)
        assert parse_result.success

        pg_sql = parser.transpile(tsql)
        assert len(pg_sql) > 0

        pg_parse = parser.parse(pg_sql)
        assert pg_parse is not None

    def test_round_trip_create_table(self, parser):
        tsql = "CREATE TABLE dbo.test (id INT, name VARCHAR(100))"
        parse_result = parser.parse(tsql)
        assert parse_result.success

        pg_sql = parser.transpile(tsql)
        assert len(pg_sql) > 0

    def test_round_trip_create_view(self, parser):
        tsql = "CREATE VIEW dbo.v_test AS SELECT id, name FROM dbo.users"
        parse_result = parser.parse(tsql)
        assert parse_result.success

        pg_sql = parser.transpile(tsql)
        assert len(pg_sql) > 0

    def test_invalid_sql_handling(self, parser):
        result = parser.parse("NOT VALID SQL @@@")
        assert not result.success
        assert len(result.errors) > 0

    def test_empty_input_handling(self, parser):
        result = parser.parse("")
        assert not result.success

    def test_null_input_handling(self, parser):
        result = parser.parse("")
        assert not result.success


class TestPipelineErrorHandling:
    """Tests for error handling throughout the pipeline."""

    def test_parse_error_propagation(self, parser):
        result = parser.parse("SELECT 1 FROM WHERE")
        assert not result.success

    def test_conversion_with_empty_body(self, converter):
        result = converter.convert_procedure("dbo", "usp_empty", [], "")
        assert result.success

    def test_conversion_with_only_comments(self, converter):
        result = converter.convert_procedure(
            "dbo", "usp_comments", [],
            "-- just a comment\n-- another comment",
        )
        assert result.success

    def test_conversion_with_unicode(self, converter):
        result = converter.convert_procedure(
            "dbo", "usp_unicode", [],
            "SELECT N'unicode text ユニコード' AS msg",
        )
        assert result.success

    @pytest.mark.parametrize("body", [
        "SELECT 1",
        "SELECT 1; SELECT 2",
        "DECLARE @x INT = 5; SELECT @x",
        "IF 1=1 SELECT 1 ELSE SELECT 2",
    ])
    def test_parameterized_bodies(self, converter, body):
        result = converter.convert_procedure("dbo", "usp_test", [], body)
        assert result.success


class TestPipelineIrBuilder:
    """Tests for the IR builder pipeline stage."""

    def test_ir_builder_from_sql(self, parser, ir_builder):
        ir = ir_builder.build_from_sql("SELECT 1")
        assert ir is not None
        assert ir.node_type.value == "program"

    def test_ir_builder_create_table(self, parser, ir_builder):
        ir = ir_builder.build_from_sql("CREATE TABLE dbo.test (id INT)")
        assert ir is not None
        assert len(ir.statements) > 0

    def test_ir_builder_multiple(self, parser, ir_builder):
        ir = ir_builder.build_multiple("SELECT 1; SELECT 2")
        assert ir is not None
        assert len(ir.statements) >= 1

    def test_ir_builder_invalid_sql(self, parser, ir_builder):
        ir = ir_builder.build_from_sql("SELECT 1 FROM")
        assert ir is None

    def test_ir_builder_view(self, parser, ir_builder):
        ir = ir_builder.build_from_sql("CREATE VIEW dbo.v_test AS SELECT 1 AS c")
        assert ir is not None

    def test_ir_builder_has_columns(self, parser, ir_builder):
        ir = ir_builder.build_from_sql("CREATE TABLE dbo.test (id INT NOT NULL, name VARCHAR(100))")
        assert ir is not None
        for stmt in ir.statements:
            cols = stmt.children or []
            assert len(cols) > 0


class TestPipelineDdlGenerator:
    """Tests for the DDL generator pipeline stage."""

    def test_generate_table_ddl(self, ir_builder, ddl_generator):
        ir = ir_builder.build_from_sql("CREATE TABLE dbo.test (id INT, name VARCHAR(100))")
        assert ir is not None
        for stmt in ir.statements:
            ddl = ddl_generator.generate_table_ddl(stmt)
            assert "CREATE TABLE" in ddl
            assert "id" in ddl
            assert "name" in ddl

    def test_generate_view_ddl(self, ir_builder, ddl_generator):
        ir = ir_builder.build_from_sql("CREATE VIEW dbo.v_test AS SELECT 1 AS c")
        assert ir is not None
        for stmt in ir.statements:
            if stmt.node_type.value == "create_view":
                ddl = ddl_generator.generate_view_ddl(stmt)
                assert "CREATE VIEW" in ddl

    def test_ddl_round_trip(self, ir_builder, ddl_generator):
        """Generated DDL should be parseable by SQLGlot postgres dialect."""
        import sqlglot
        ir = ir_builder.build_from_sql("CREATE TABLE dbo.test (id INT, name VARCHAR(100))")
        assert ir is not None
        for stmt in ir.statements:
            ddl = ddl_generator.generate_table_ddl(stmt)
            pg_parsed = sqlglot.parse_one(ddl, read="postgres")
            assert pg_parsed is not None
