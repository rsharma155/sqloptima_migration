"""
Module: tests/unit/test_dynamic_sql_procedure_converter.py
Purpose: Unit tests for dynamic SQL procedure conversion pipeline.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from pathlib import Path

import pytest

from domains.transpilation.dynamic_sql.converter import (
    Converter,
    DynamicSqlProcedureConverter,
)
from domains.transpilation.dynamic_sql.prepass import (
    apply_dynamic_sql_prepass,
    has_resolvable_dynamic_sql,
)
from domains.transpilation.dynamic_sql.models import (
    ConditionalPredicate,
    FragmentType,
    Severity,
)
from domains.transpilation.dynamic_sql.normalizer import SqlNormalizer
from domains.transpilation.dynamic_sql.resolver import DynamicSqlResolver
from domains.transpilation.dynamic_sql.symbol_table import SymbolEntry, SymbolTable
from domains.transpilation.dynamic_sql.type_mapper import TypeMapper
from domains.transpilation.procedural_converter import ProceduralConverter

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "dynamic_sql"


# ---------------------------------------------------------------------------
# Symbol Table Tests
# ---------------------------------------------------------------------------


class TestSymbolTable:
    def test_declare_and_get(self):
        table = SymbolTable()
        entry = table.declare("@sql", "NVARCHAR(MAX)")
        assert table.get("@sql") is entry
        assert table.get("@SQL") is entry
        assert table.get("@missing") is None

    def test_scope_push_pop(self):
        table = SymbolTable()
        table.declare("@a")
        table.push_scope()
        table.declare("@b")
        assert table.get("@b") is not None
        table.pop_scope()
        assert table.get("@b") is None
        assert table.get("@a") is not None


class TestSymbolEntry:
    def test_add_literal(self):
        e = SymbolEntry("@sql")
        e.add_literal("SELECT *")
        e.add_literal(" FROM Orders")
        assert e.get_resolved_sql() == "SELECT * FROM Orders"

    def test_add_variable(self):
        e = SymbolEntry("@sql")
        e.add_literal("WHERE id = ")
        e.add_variable("@id")
        assert e.get_resolved_sql() == "WHERE id = @id"

    def test_get_parameterized_vars(self):
        e = SymbolEntry("@sql")
        e.add_literal("SELECT * FROM t WHERE id = ")
        e.add_variable("@id")
        e.add_literal(" AND status = ")
        e.add_variable("@status")
        assert e.get_parameterized_vars() == {"@id", "@status"}


class TestSymbolTableResolve:
    def test_resolve_simple(self):
        table = SymbolTable()
        entry = table.declare("@sql")
        entry.add_literal("SELECT * FROM Orders WHERE id = ")
        entry.add_variable("@id")
        resolved = table.resolve_sql_variable("@sql")
        text = "".join(f.value for f in resolved)
        assert "SELECT * FROM Orders" in text
        assert "@id" in text

    def test_resolve_chained(self):
        table = SymbolTable()
        e1 = table.declare("@part1")
        e1.add_literal(" AND status = ")
        e1.add_variable("@status")

        e2 = table.declare("@sql")
        e2.add_literal("SELECT * FROM t WHERE 1=1")
        e2.add_variable("@part1")
        resolved = table.resolve_sql_variable("@sql")
        text = "".join(f.value for f in resolved)
        assert "SELECT * FROM t WHERE 1=1" in text
        assert "status" in text
        assert "@status" in text


# ---------------------------------------------------------------------------
# Resolver Tests
# ---------------------------------------------------------------------------


class TestDynamicSqlResolver:
    def test_resolve_exec_literal(self):
        table = SymbolTable()
        resolver = DynamicSqlResolver(table)
        stmt = resolver.resolve_statement("EXEC('SELECT * FROM Orders')")
        assert stmt.normalized_sql == "SELECT * FROM Orders"

    def test_resolve_exec_variable(self):
        table = SymbolTable()
        e = table.declare("@sql", "NVARCHAR(MAX)")
        e.add_literal("SELECT * FROM Users WHERE id = ")
        e.add_variable("@id")
        resolver = DynamicSqlResolver(table)
        stmt = resolver.resolve_statement("EXEC @sql")
        assert "SELECT * FROM Users" in stmt.normalized_sql
        assert "@id" in stmt.normalized_sql

    def test_resolve_execute(self):
        table = SymbolTable()
        resolver = DynamicSqlResolver(table)
        stmt = resolver.resolve_statement("EXECUTE('SELECT 1')")
        assert stmt.normalized_sql == "SELECT 1"

    def test_non_exec_statement(self):
        table = SymbolTable()
        resolver = DynamicSqlResolver(table)
        stmt = resolver.resolve_statement("SELECT * FROM Orders")
        assert stmt.normalized_sql == "SELECT * FROM Orders"

    def test_sp_executesql_with_literal(self):
        table = SymbolTable()
        resolver = DynamicSqlResolver(table)
        stmt = resolver.resolve_statement(
            "sp_executesql N'SELECT * FROM Orders WHERE id = @id', N'@id INT', @id = 1"
        )
        assert stmt.uses_sp_executesql
        assert "SELECT * FROM Orders" in stmt.normalized_sql

    def test_sp_executesql_with_variable(self):
        table = SymbolTable()
        e = table.declare("@sql", "NVARCHAR(MAX)")
        e.add_literal("SELECT * FROM Products")
        resolver = DynamicSqlResolver(table)
        stmt = resolver.resolve_statement(
            "sp_executesql @sql, N'@id INT', @id = 1"
        )
        assert "SELECT * FROM Products" in stmt.normalized_sql

    def test_sp_executesql_params_extracted(self):
        table = SymbolTable()
        resolver = DynamicSqlResolver(table)
        stmt = resolver.resolve_statement(
            "sp_executesql N'SELECT * FROM T WHERE id = @id', N'@id INT', @id = 42"
        )
        assert "@id" in stmt.params
        assert stmt.params["@id"] == "42"


# ---------------------------------------------------------------------------
# Normalizer Tests
# ---------------------------------------------------------------------------


class TestSqlNormalizer:
    def test_remove_where_1_equals_1(self):
        normalizer = SqlNormalizer(SymbolTable())
        result = normalizer.normalize(
            "SELECT * FROM Orders WHERE 1=1 AND status = 'active'"
        )
        assert "1=1" not in result

    def test_clean_n_prefix(self):
        normalizer = SqlNormalizer(SymbolTable())
        result = normalizer.normalize("SELECT * FROM T WHERE name = N'hello'")
        assert "N'" not in result
        assert "'hello'" in result or "hello" in result

    def test_dynamic_order_by_warning(self):
        normalizer = SqlNormalizer(SymbolTable())
        normalizer.normalize("SELECT * FROM T ORDER BY @SortColumn")
        codes = [w.code for w in normalizer.get_warnings()]
        assert "DYNAMIC_ORDER_BY" in codes

    def test_dynamic_table_warning(self):
        normalizer = SqlNormalizer(SymbolTable())
        normalizer.normalize("SELECT * FROM @TableName")
        codes = [w.code for w in normalizer.get_warnings()]
        assert "DYNAMIC_TABLE_REFERENCE" in codes

    def test_conditional_predicates(self):
        normalizer = SqlNormalizer(SymbolTable())
        predicates = [
            ConditionalPredicate("@id", "IS NOT NULL", "AND id = @id")
        ]
        result = normalizer.apply_conditional_predicates(predicates)
        assert "@id IS NULL" in result
        assert "id = @id" in result


# ---------------------------------------------------------------------------
# Type Mapper Tests
# ---------------------------------------------------------------------------


class TestTypeMapper:
    def setup_method(self):
        self.mapper = TypeMapper()

    def test_int_mapping(self):
        assert self.mapper.map_data_type("INT") == "INTEGER"

    def test_nvarchar_mapping(self):
        assert self.mapper.map_data_type("NVARCHAR(MAX)") == "TEXT"

    def test_getdate_mapping(self):
        result = self.mapper.map_function("GETDATE")
        assert "CURRENT_TIMESTAMP" in result

    def test_unmapped_function_warning(self):
        self.mapper.map_function("MY_CUSTOM_FUNC")
        warnings = self.mapper.get_warnings()
        assert len(warnings) == 1
        assert warnings[0].code == "UNMAPPED_FUNCTION"


# ---------------------------------------------------------------------------
# Full Converter Integration Tests
# ---------------------------------------------------------------------------


class TestDynamicSqlProcedureConverter:
    def setup_method(self):
        self.converter = DynamicSqlProcedureConverter()

    def test_convert_simple_select(self):
        result = self.converter.convert_sql("SELECT * FROM Orders")
        assert result.success
        assert result.target_sql is not None

    def test_convert_exec_literal(self):
        result = self.converter.convert_sql("EXEC('SELECT * FROM Orders')")
        assert result.success
        assert "SELECT" in result.target_sql

    def test_convert_procedure_with_params(self):
        sql = """
        CREATE PROC dbo.GetOrders
            @CustomerId INT,
            @Status VARCHAR(20)
        AS
        BEGIN
            DECLARE @sql NVARCHAR(MAX)
            SET @sql = 'SELECT * FROM Orders WHERE 1=1'
            IF @CustomerId IS NOT NULL
                SET @sql = @sql + ' AND CustomerId = ' + CAST(@CustomerId AS VARCHAR)
            IF @Status IS NOT NULL
                SET @sql = @sql + ' AND Status = ''' + @Status + ''''
            EXEC(@sql)
        END
        """
        result = self.converter.convert_sql(sql)
        assert result.success, f"Conversion failed: {result.errors}"
        assert result.procedure_name == "dbo.GetOrders"
        assert "FUNCTION" in result.target_sql.upper()

    def test_convert_sp_executesql(self):
        sql = """
        CREATE PROC dbo.GetProduct
            @ProductId INT
        AS
        BEGIN
            DECLARE @sql NVARCHAR(MAX)
            SET @sql = 'SELECT * FROM Products WHERE ProductId = @ProductId'
            EXEC sp_executesql @sql, N'@ProductId INT', @ProductId = @ProductId
        END
        """
        result = self.converter.convert_sql(sql)
        assert result.success
        assert "FUNCTION" in result.target_sql.upper()

    def test_complex_dynamic_procedure(self):
        sql = """
        CREATE PROC dbo.SearchOrders
            @CustomerId INT = NULL,
            @Status VARCHAR(20) = NULL,
            @SortColumn VARCHAR(50) = 'OrderDate',
            @SortDirection VARCHAR(4) = 'DESC'
        AS
        BEGIN
            DECLARE @sql NVARCHAR(MAX)
            SET @sql = 'SELECT OrderId FROM Orders WHERE 1=1'
            IF @CustomerId IS NOT NULL
                SET @sql = @sql + ' AND CustomerId = ' + CAST(@CustomerId AS VARCHAR)
            IF @Status IS NOT NULL
                SET @sql = @sql + ' AND Status = ''' + @Status + ''''
            SET @sql = @sql + ' ORDER BY ' + @SortColumn + ' ' + @SortDirection
            EXEC(@sql)
        END
        """
        result = self.converter.convert_sql(sql)
        assert result.success, f"Conversion failed: {result.errors}"
        assert "FUNCTION" in result.target_sql.upper()

    def test_converter_alias(self):
        assert Converter is DynamicSqlProcedureConverter


class TestProceduralConverterIntegration:
    _DYNAMIC_SP = """
        CREATE PROC dbo.GetProduct
            @ProductId INT
        AS
        BEGIN
            DECLARE @sql NVARCHAR(MAX)
            SET @sql = 'SELECT * FROM Products WHERE ProductId = @ProductId'
            EXEC sp_executesql @sql, N'@ProductId INT', @ProductId = @ProductId
        END
        """

    def test_auto_and_procedure_paths_match(self):
        converter = ProceduralConverter(enable_phase_enhancements=False)
        auto = converter.auto_convert(self._DYNAMIC_SP)
        explicit = converter.convert_procedure("dbo", "GetProduct", [], self._DYNAMIC_SP)
        assert auto.success and explicit.success
        assert auto.converted_sql == explicit.converted_sql

    def test_unified_pipeline_uses_dynamic_sql_prepass(self):
        result = ProceduralConverter(enable_phase_enhancements=False).auto_convert(self._DYNAMIC_SP)
        assert result.success
        assert any("Dynamic SQL pre-pass" in w for w in result.warnings)
        assert "GetProduct" in result.converted_sql
        assert "CREATE OR REPLACE" in result.converted_sql.upper()

    def test_has_resolvable_dynamic_sql(self):
        assert has_resolvable_dynamic_sql("EXEC sp_executesql @sql")
        assert not has_resolvable_dynamic_sql("SELECT 1")

    def test_prepass_noop_for_static_sql(self):
        result = apply_dynamic_sql_prepass("SELECT 1")
        assert not result.applied
        assert result.sql == "SELECT 1"


@pytest.mark.parametrize(
    "fixture_name",
    [
        "001_dynamic_search_procedure.sql",
        "011_dynamic_parameterized_order_by.sql",
        "004_dynamic_merge_upsert.sql",
    ],
)
def test_sqlserver_sp_fixtures_convert(fixture_name: str):
    """Regression: sample SQL Server dynamic SP fixtures produce PG output."""
    path = _FIXTURE_DIR / fixture_name
    if not path.exists():
        pytest.skip(f"Fixture removed: {fixture_name}")
    sql = path.read_text(encoding="utf-8")
    result = ProceduralConverter(enable_phase_enhancements=False).auto_convert(sql)
    assert result.success, f"{fixture_name} failed: {result.errors}"
    assert result.converted_sql
    assert "CREATE OR REPLACE" in result.converted_sql.upper()
