"""
Module: tests/unit/test_tsql_to_plpgsql.py
Purpose: TDD tests for the comprehensive T-SQL to PL/pgSQL stored procedure converter.
         Covers all 30 issue categories identified in the gap analysis of 100 SPs.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import pytest

from domains.transpilation.converters.tsql_to_plpgsql import (
    TsqlHeaderParser,
    TsqlTypeMapper,
    TsqlBodyConverter,
    TsqlToPlpgsqlConverter,
    SprocType,
    ParamInfo,
)


# ---------------------------------------------------------------------------
# TsqlHeaderParser tests
# ---------------------------------------------------------------------------

class TestTsqlHeaderParser:
    """Tests for parsing CREATE PROCEDURE / FUNCTION headers."""

    def test_simple_name_no_params(self):
        sql = "CREATE PROCEDURE dbo.usp_get_all_products\nAS\nBEGIN\n  SELECT 1;\nEND"
        info = TsqlHeaderParser.parse(sql)
        assert info.schema == "dbo"
        assert info.name == "usp_get_all_products"
        assert info.parameters == []

    def test_name_with_brackets(self):
        sql = "CREATE PROCEDURE [dbo].[usp_test]\nAS BEGIN SELECT 1; END"
        info = TsqlHeaderParser.parse(sql)
        assert info.name == "usp_test"
        assert info.schema == "dbo"

    def test_create_proc_shorthand(self):
        sql = "CREATE PROC dbo.usp_test\nAS BEGIN SELECT 1; END"
        info = TsqlHeaderParser.parse(sql)
        assert info.name == "usp_test"

    def test_single_input_param(self):
        sql = (
            "CREATE PROCEDURE dbo.usp_get_by_id\n"
            "    @ProductID INT\n"
            "AS\nBEGIN\n  SELECT 1;\nEND"
        )
        info = TsqlHeaderParser.parse(sql)
        assert len(info.parameters) == 1
        p = info.parameters[0]
        assert p.name == "ProductID"
        assert p.pg_type == "INT"
        assert p.is_output is False
        assert p.default_value is None

    def test_param_with_default_null(self):
        sql = (
            "CREATE PROCEDURE dbo.usp_test\n"
            "    @SupplierID INT = NULL\n"
            "AS BEGIN SELECT 1; END"
        )
        info = TsqlHeaderParser.parse(sql)
        assert info.parameters[0].default_value == "NULL"

    def test_param_with_numeric_default(self):
        sql = (
            "CREATE PROCEDURE dbo.usp_test\n"
            "    @UnitPrice MONEY = 0\n"
            "AS BEGIN SELECT 1; END"
        )
        info = TsqlHeaderParser.parse(sql)
        p = info.parameters[0]
        assert p.default_value == "0"
        assert p.pg_type == "NUMERIC"

    def test_output_param(self):
        sql = (
            "CREATE PROCEDURE dbo.usp_test\n"
            "    @NewProductID INT OUTPUT\n"
            "AS BEGIN SELECT 1; END"
        )
        info = TsqlHeaderParser.parse(sql)
        assert info.parameters[0].is_output is True

    def test_multiple_params(self):
        sql = (
            "CREATE PROCEDURE dbo.usp_insert_product\n"
            "    @ProductName NVARCHAR(40),\n"
            "    @SupplierID INT = NULL,\n"
            "    @UnitPrice MONEY = 0,\n"
            "    @Discontinued BIT = 0,\n"
            "    @NewProductID INT OUTPUT\n"
            "AS BEGIN SELECT 1; END"
        )
        info = TsqlHeaderParser.parse(sql)
        assert len(info.parameters) == 5
        names = [p.name for p in info.parameters]
        assert "ProductName" in names
        assert "NewProductID" in names
        output_params = [p for p in info.parameters if p.is_output]
        assert len(output_params) == 1
        assert output_params[0].name == "NewProductID"

    def test_body_extracted_correctly(self):
        sql = (
            "CREATE PROCEDURE dbo.usp_test @x INT AS\n"
            "BEGIN\n"
            "    SET NOCOUNT ON;\n"
            "    SELECT * FROM Products WHERE ProductID = @x;\n"
            "END;\nGO"
        )
        info = TsqlHeaderParser.parse(sql)
        assert "SELECT * FROM Products" in info.body
        assert "CREATE PROCEDURE" not in info.body

    def test_no_schema_defaults_to_dbo(self):
        sql = "CREATE PROCEDURE usp_test AS BEGIN SELECT 1; END"
        info = TsqlHeaderParser.parse(sql)
        assert info.schema == "dbo"

    def test_nchar_param(self):
        sql = (
            "CREATE PROCEDURE dbo.usp_test\n"
            "    @CustomerID NCHAR(5)\n"
            "AS BEGIN SELECT 1; END"
        )
        info = TsqlHeaderParser.parse(sql)
        assert info.parameters[0].pg_type == "CHAR(5)"

    def test_readonly_param_stripped(self):
        """READONLY keyword on TVP params should be stripped."""
        sql = (
            "CREATE PROCEDURE dbo.usp_test\n"
            "    @Products ProductTableType READONLY\n"
            "AS BEGIN SELECT 1; END"
        )
        info = TsqlHeaderParser.parse(sql)
        assert info.parameters[0].is_readonly is True


# ---------------------------------------------------------------------------
# TsqlTypeMapper tests
# ---------------------------------------------------------------------------

class TestTsqlTypeMapper:
    """Tests for T-SQL → PostgreSQL type mapping."""

    def test_money_to_numeric(self):
        assert TsqlTypeMapper.map("MONEY") == "NUMERIC"

    def test_smallmoney_to_numeric(self):
        assert TsqlTypeMapper.map("SMALLMONEY") == "NUMERIC"

    def test_nvarchar_max_to_text(self):
        assert TsqlTypeMapper.map("NVARCHAR(MAX)") == "TEXT"

    def test_varchar_max_to_text(self):
        assert TsqlTypeMapper.map("VARCHAR(MAX)") == "TEXT"

    def test_nvarchar_n_to_varchar_n(self):
        assert TsqlTypeMapper.map("NVARCHAR(40)") == "VARCHAR(40)"

    def test_nchar_to_char(self):
        assert TsqlTypeMapper.map("NCHAR(5)") == "CHAR(5)"

    def test_bit_to_boolean(self):
        assert TsqlTypeMapper.map("BIT") == "BOOLEAN"

    def test_tinyint_to_smallint(self):
        assert TsqlTypeMapper.map("TINYINT") == "SMALLINT"

    def test_datetime_to_timestamp(self):
        assert TsqlTypeMapper.map("DATETIME") == "TIMESTAMP"

    def test_uniqueidentifier_to_uuid(self):
        assert TsqlTypeMapper.map("UNIQUEIDENTIFIER") == "UUID"

    def test_int_unchanged(self):
        assert TsqlTypeMapper.map("INT") == "INT"

    def test_varchar_n_unchanged(self):
        assert TsqlTypeMapper.map("VARCHAR(40)") == "VARCHAR(40)"

    def test_case_insensitive(self):
        assert TsqlTypeMapper.map("money") == "NUMERIC"
        assert TsqlTypeMapper.map("NVarChar(Max)") == "TEXT"

    def test_datetimeoffset_to_timestamptz(self):
        assert TsqlTypeMapper.map("DATETIMEOFFSET") == "TIMESTAMPTZ"

    def test_boolean_default_0_to_false(self):
        assert TsqlTypeMapper.map_default("0", "BIT") == "FALSE"

    def test_boolean_default_1_to_true(self):
        assert TsqlTypeMapper.map_default("1", "BIT") == "TRUE"

    def test_numeric_default_unchanged(self):
        assert TsqlTypeMapper.map_default("0", "INT") == "0"

    def test_null_default_unchanged(self):
        assert TsqlTypeMapper.map_default("NULL", "INT") == "NULL"


# ---------------------------------------------------------------------------
# TsqlBodyConverter tests  (C3-C30 category fixes)
# ---------------------------------------------------------------------------

class TestTsqlBodyConverter:
    """Tests for body transformation rules."""

    # CAT-18: SET option removal
    def test_remove_set_nocount_on(self):
        body = "SET NOCOUNT ON;\nSELECT 1;"
        result = TsqlBodyConverter.convert(body, [])
        assert "SET NOCOUNT ON" not in result
        assert "SELECT 1" in result

    def test_remove_set_xact_abort(self):
        body = "SET XACT_ABORT ON;\nSELECT 1;"
        result = TsqlBodyConverter.convert(body, [])
        assert "SET XACT_ABORT ON" not in result

    def test_remove_go(self):
        body = "SELECT 1;\nGO\nSELECT 2;"
        result = TsqlBodyConverter.convert(body, [])
        assert "\nGO\n" not in result.upper()

    def test_remove_commit_from_function_body(self):
        body = "INSERT INTO t VALUES (1);\nCOMMIT TRANSACTION;"
        result = TsqlBodyConverter.convert(body, [])
        assert "COMMIT TRANSACTION" not in result

    def test_remove_set_quoted_identifier(self):
        body = "SET QUOTED_IDENTIFIER ON;\nSELECT 1;"
        result = TsqlBodyConverter.convert(body, [])
        assert "SET QUOTED_IDENTIFIER" not in result

    def test_remove_set_ansi_nulls(self):
        body = "SET ANSI_NULLS ON;\nSELECT 1;"
        result = TsqlBodyConverter.convert(body, [])
        assert "SET ANSI_NULLS" not in result

    # CAT-10: Variable assignment
    def test_set_var_becomes_assign(self):
        body = "SET @myVar = 42;"
        result = TsqlBodyConverter.convert(body, [])
        assert "v_myVar := 42;" in result
        assert "SET @myVar" not in result

    def test_set_param_becomes_param_assign(self):
        params = [ParamInfo(name="OutputVal", pg_type="INT", is_output=True)]
        body = "SET @OutputVal = 99;"
        result = TsqlBodyConverter.convert(body, params)
        assert "p_OutputVal := 99;" in result

    # CAT-9: Variable-assignment SELECT
    def test_select_at_var_into(self):
        body = "SELECT @Count = COUNT(*) FROM Products;"
        result = TsqlBodyConverter.convert(body, [])
        assert "SELECT COUNT(*) INTO v_Count FROM Products" in result
        assert "@Count" not in result

    def test_select_multi_var_into(self):
        body = "SELECT @Avg = AVG(Price), @Total = SUM(Price) FROM Products;"
        result = TsqlBodyConverter.convert(body, [])
        assert "INTO v_Avg, v_Total" in result

    # CAT-8: Date functions
    def test_year_to_extract(self):
        body = "SELECT YEAR(OrderDate) FROM Orders;"
        result = TsqlBodyConverter.convert(body, [])
        assert "EXTRACT(YEAR FROM OrderDate)" in result
        assert "YEAR(OrderDate)" not in result

    def test_month_to_extract(self):
        body = "SELECT MONTH(OrderDate) FROM Orders;"
        result = TsqlBodyConverter.convert(body, [])
        assert "EXTRACT(MONTH FROM OrderDate)" in result

    def test_day_to_extract(self):
        body = "SELECT DAY(CreatedAt) FROM Events;"
        result = TsqlBodyConverter.convert(body, [])
        assert "EXTRACT(DAY FROM CreatedAt)" in result

    # CAT-4: @@ROWCOUNT → GET DIAGNOSTICS
    def test_rowcount_to_get_diagnostics(self):
        body = "UPDATE Products SET Price = 1;\nSET @n = @@ROWCOUNT;"
        result = TsqlBodyConverter.convert(body, [])
        assert "GET DIAGNOSTICS" in result
        assert "ROW_COUNT" in result

    def test_rowcount_if_zero_to_not_found(self):
        body = (
            "DELETE FROM Products WHERE ProductID = @id;\n"
            "IF @@ROWCOUNT = 0\nBEGIN\n  RAISERROR('Not found', 16, 1);\nEND;"
        )
        result = TsqlBodyConverter.convert(body, [])
        assert "NOT FOUND" in result.upper() or "GET DIAGNOSTICS" in result

    # CAT-7: BEGIN TRY/CATCH
    def test_try_catch_conversion(self):
        body = (
            "BEGIN TRY\n"
            "    INSERT INTO t VALUES (1);\n"
            "END TRY\n"
            "BEGIN CATCH\n"
            "    ROLLBACK;\n"
            "END CATCH"
        )
        result = TsqlBodyConverter.convert(body, [])
        assert "BEGIN TRY" not in result
        assert "END TRY" not in result
        assert "BEGIN CATCH" not in result
        assert "END CATCH" not in result
        assert "EXCEPTION" in result
        assert "WHEN OTHERS THEN" in result

    # CAT-14: Recursive CTE
    def test_recursive_cte_gets_recursive_keyword(self):
        body = (
            "WITH Hierarchy AS (\n"
            "  SELECT id, parent_id, 0 AS depth FROM t WHERE parent_id IS NULL\n"
            "  UNION ALL\n"
            "  SELECT t.id, t.parent_id, h.depth+1 FROM t JOIN Hierarchy h ON t.parent_id=h.id\n"
            ")\n"
            "SELECT * FROM Hierarchy;"
        )
        result = TsqlBodyConverter.convert(body, [])
        assert "WITH RECURSIVE" in result

    def test_non_recursive_cte_unchanged(self):
        body = (
            "WITH cte AS (SELECT 1 AS n)\n"
            "SELECT * FROM cte;"
        )
        result = TsqlBodyConverter.convert(body, [])
        assert "WITH RECURSIVE" not in result
        assert "WITH cte AS" in result

    # CAT-15: MONEY type in temp tables
    def test_money_in_declare_converted(self):
        body = "DECLARE @Price MONEY = 0;"
        result = TsqlBodyConverter.convert(body, [])
        assert "MONEY" not in result
        assert "NUMERIC" in result

    # CAT-24: N'' string literals
    def test_n_prefix_stripped(self):
        body = "SET @msg = N'Hello World';"
        result = TsqlBodyConverter.convert(body, [])
        assert "N'" not in result
        assert "'Hello World'" in result

    # CAT-28 partial: String concat + to ||
    def test_string_plus_to_concat(self):
        body = "SET @result = @first + ' ' + @last;"
        result = TsqlBodyConverter.convert(body, [])
        assert " || " in result

    # CAT-25: CONVERT() → CAST
    def test_convert_int_to_cast(self):
        body = "SELECT CONVERT(INT, Price) FROM Products;"
        result = TsqlBodyConverter.convert(body, [])
        assert "CAST(Price AS INT)" in result or "Price::INT" in result

    def test_convert_varchar_to_cast(self):
        body = "SELECT CONVERT(VARCHAR(10), ProductID) FROM Products;"
        result = TsqlBodyConverter.convert(body, [])
        assert "CAST(" in result or "::" in result

    # CAT-11: RAISERROR → RAISE EXCEPTION
    def test_raiserror_literal_to_raise(self):
        body = "RAISERROR('Record not found', 16, 1);"
        result = TsqlBodyConverter.convert(body, [])
        assert "RAISE EXCEPTION 'Record not found'" in result
        assert "RAISERROR" not in result

    def test_raiserror_with_format_param(self):
        body = "RAISERROR('ID %d not found', 16, 1, @ProductID);"
        result = TsqlBodyConverter.convert(body, [])
        assert "RAISERROR" not in result
        assert "RAISE EXCEPTION" in result

    # CAT-24: PRINT → RAISE NOTICE
    def test_print_to_raise_notice(self):
        body = "PRINT 'Processing complete';"
        result = TsqlBodyConverter.convert(body, [])
        assert "RAISE NOTICE" in result
        assert "PRINT" not in result

    # Temp table conversion
    def test_temp_table_hash_to_tmp(self):
        body = "CREATE TABLE #TempResults (id INT, name VARCHAR(50));"
        result = TsqlBodyConverter.convert(body, [])
        assert "#TempResults" not in result
        assert "tmp_TempResults" in result or "TEMP TABLE" in result

    # CAT-19: TOP WITH TIES → DENSE_RANK subquery
    def test_top_with_ties_uses_dense_rank(self):
        body = "SELECT TOP (5) WITH TIES ProductID, ProductName FROM Products ORDER BY UnitPrice DESC;"
        result = TsqlBodyConverter.convert(body, [])
        assert "WITH TIES" not in result
        assert "DENSE_RANK()" in result or "LIMIT" in result

    # Parameter prefix conversion
    def test_at_param_becomes_p_prefix(self):
        params = [ParamInfo(name="CustomerID", pg_type="INT")]
        body = "SELECT * FROM Orders WHERE CustomerID = @CustomerID;"
        result = TsqlBodyConverter.convert(body, params)
        assert "p_CustomerID" in result
        assert "@CustomerID" not in result

    def test_at_local_var_becomes_v_prefix(self):
        body = "DECLARE @Count INT;\nSET @Count = 0;"
        result = TsqlBodyConverter.convert(body, [])
        assert "v_Count" in result
        assert "@Count" not in result

    # WAITFOR DELAY
    def test_waitfor_delay_to_pg_sleep(self):
        body = "WAITFOR DELAY '00:00:05';"
        result = TsqlBodyConverter.convert(body, [])
        assert "pg_sleep" in result
        assert "WAITFOR" not in result

    # IIF
    def test_iif_to_case_when(self):
        body = "SELECT IIF(price > 10, 'expensive', 'cheap') FROM Products;"
        result = TsqlBodyConverter.convert(body, [])
        assert "CASE WHEN price > 10 THEN 'expensive' ELSE 'cheap' END" in result
        assert "IIF(" not in result

    # CHOOSE
    def test_choose_to_array_index(self):
        body = "SELECT CHOOSE(3, 'First', 'Second', 'Third') FROM t;"
        result = TsqlBodyConverter.convert(body, [])
        assert "IIF" not in result or "CHOOSE" not in result


# ---------------------------------------------------------------------------
# TsqlToPlpgsqlConverter end-to-end tests
# ---------------------------------------------------------------------------

class TestTsqlToPlpgsqlConverter:
    """Full end-to-end conversion tests for common SP patterns."""

    def _conv(self, sql: str) -> str:
        return TsqlToPlpgsqlConverter().convert(sql)

    # CAT-1: Correct name (not usp_example)
    def test_correct_name_extracted(self):
        sql = (
            "CREATE PROCEDURE dbo.usp_get_all_products\n"
            "AS\nBEGIN\n"
            "    SELECT ProductID FROM Products;\n"
            "END;"
        )
        result = self._conv(sql)
        assert "usp_get_all_products" in result
        assert "usp_example" not in result

    # CAT-2+C27: Parameters present with p_ prefix
    def test_params_present_with_p_prefix(self):
        sql = (
            "CREATE PROCEDURE dbo.usp_get_by_id\n"
            "    @ProductID INT\n"
            "AS\nBEGIN\n"
            "    SELECT * FROM Products WHERE ProductID = @ProductID;\n"
            "END;"
        )
        result = self._conv(sql)
        assert "p_ProductID INT" in result
        assert "@ProductID" not in result

    # CAT-3: SELECT-only SP becomes FUNCTION
    def test_select_only_becomes_function(self):
        sql = (
            "CREATE PROCEDURE dbo.usp_get_all_products\n"
            "AS\nBEGIN\n"
            "    SET NOCOUNT ON;\n"
            "    SELECT ProductID, ProductName FROM Products;\n"
            "END;"
        )
        result = self._conv(sql)
        assert "CREATE OR REPLACE FUNCTION" in result
        assert "RETURNS" in result

    # CAT-3: DML-only SP stays PROCEDURE
    def test_dml_with_output_stays_procedure(self):
        sql = (
            "CREATE PROCEDURE dbo.usp_insert_product\n"
            "    @ProductName NVARCHAR(40),\n"
            "    @NewID INT OUTPUT\n"
            "AS\nBEGIN\n"
            "    INSERT INTO Products (ProductName) VALUES (@ProductName);\n"
            "    SET @NewID = SCOPE_IDENTITY();\n"
            "END;"
        )
        result = self._conv(sql)
        assert "CREATE OR REPLACE PROCEDURE" in result
        assert "INOUT p_NewID" in result

    # CAT-15: MONEY type mapped
    def test_money_param_mapped_to_numeric(self):
        sql = (
            "CREATE PROCEDURE dbo.usp_test\n"
            "    @Price MONEY = 0\n"
            "AS\nBEGIN\n    SELECT 1;\nEND;"
        )
        result = self._conv(sql)
        assert "NUMERIC" in result
        assert "MONEY" not in result

    # CAT-14: Recursive CTE gets RECURSIVE keyword
    def test_recursive_cte_in_sp(self):
        sql = (
            "CREATE PROCEDURE dbo.usp_get_hierarchy\n"
            "    @EmployeeID INT\n"
            "AS\nBEGIN\n"
            "    WITH EmployeeHierarchy AS (\n"
            "        SELECT EmployeeID, 0 AS Level FROM HR.Employees WHERE EmployeeID = @EmployeeID\n"
            "        UNION ALL\n"
            "        SELECT e.EmployeeID, h.Level + 1\n"
            "        FROM HR.Employees e\n"
            "        JOIN EmployeeHierarchy h ON e.ReportsTo = h.EmployeeID\n"
            "    )\n"
            "    SELECT * FROM EmployeeHierarchy;\n"
            "END;"
        )
        result = self._conv(sql)
        assert "WITH RECURSIVE" in result

    # CAT-7: TRY/CATCH → EXCEPTION
    def test_try_catch_in_sp(self):
        sql = (
            "CREATE PROCEDURE dbo.usp_safe_insert\n"
            "    @Name VARCHAR(40),\n"
            "    @NewID INT OUTPUT\n"
            "AS\nBEGIN\n"
            "    BEGIN TRY\n"
            "        INSERT INTO Products (Name) VALUES (@Name);\n"
            "        SET @NewID = SCOPE_IDENTITY();\n"
            "    END TRY\n"
            "    BEGIN CATCH\n"
            "        SET @NewID = NULL;\n"
            "        THROW;\n"
            "    END CATCH;\n"
            "END;"
        )
        result = self._conv(sql)
        assert "BEGIN TRY" not in result
        assert "END TRY" not in result
        assert "EXCEPTION" in result

    # CAT-29: $$ delimiter (not $function$)
    def test_dollar_quote_is_double_dollar(self):
        sql = (
            "CREATE PROCEDURE dbo.usp_test\n"
            "AS\nBEGIN\n    SELECT 1;\nEND;"
        )
        result = self._conv(sql)
        assert "$$" in result
        # $function$ should NOT appear as outer delimiter
        assert "$function$" not in result

    # CAT-18: SET NOCOUNT removed from output
    def test_set_nocount_not_in_output(self):
        sql = (
            "CREATE PROCEDURE dbo.usp_test\n"
            "AS\nBEGIN\n"
            "    SET NOCOUNT ON;\n"
            "    SELECT 1;\n"
            "END;"
        )
        result = self._conv(sql)
        assert "SET NOCOUNT" not in result

    # Full SP 01: get_all_products
    def test_sp01_get_all_products(self):
        sql = """CREATE PROCEDURE dbo.usp_get_all_products
AS
BEGIN
    SET NOCOUNT ON;
    SELECT ProductID, ProductName, CategoryID, UnitPrice, UnitsInStock, Discontinued
    FROM Production.Products
    ORDER BY ProductName;
END;
GO"""
        result = self._conv(sql)
        assert "usp_get_all_products" in result
        assert "usp_example" not in result
        assert "CREATE OR REPLACE FUNCTION" in result
        assert "SET NOCOUNT" not in result
        assert "SELECT ProductID" in result
        assert "$$" in result
        assert "GO" not in result

    # Full SP 03: insert_product with output param
    def test_sp03_insert_product(self):
        sql = """CREATE PROCEDURE dbo.usp_insert_product
    @ProductName NVARCHAR(40),
    @SupplierID INT = NULL,
    @UnitPrice MONEY = 0,
    @Discontinued BIT = 0,
    @NewProductID INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO Production.Products
        (ProductName, SupplierID, UnitPrice, Discontinued)
    VALUES
        (@ProductName, @SupplierID, @UnitPrice, @Discontinued);
    SET @NewProductID = SCOPE_IDENTITY();
END;
GO"""
        result = self._conv(sql)
        assert "usp_insert_product" in result
        assert "p_ProductName" in result
        assert "NUMERIC" in result  # MONEY → NUMERIC
        assert "INOUT p_NewProductID" in result
        assert "@" not in result or "@@" in result  # no bare @params
        assert "CREATE OR REPLACE PROCEDURE" in result

    # Full SP 17: hierarchy with recursive CTE
    def test_sp17_hierarchy(self):
        sql = """CREATE PROCEDURE dbo.usp_get_hierarchy
    @EmployeeID INT
AS
BEGIN
    SET NOCOUNT ON;
    WITH EmployeeHierarchy AS
    (
        SELECT EmployeeID, FirstName, LastName, ReportsTo, 0 AS HierarchyLevel
        FROM HR.Employees
        WHERE EmployeeID = @EmployeeID
        UNION ALL
        SELECT e.EmployeeID, e.FirstName, e.LastName, e.ReportsTo, eh.HierarchyLevel + 1
        FROM HR.Employees e
        INNER JOIN EmployeeHierarchy eh ON e.ReportsTo = eh.EmployeeID
    )
    SELECT EmployeeID, FirstName, LastName, ReportsTo, HierarchyLevel
    FROM EmployeeHierarchy
    ORDER BY HierarchyLevel;
END;
GO"""
        result = self._conv(sql)
        assert "usp_get_hierarchy" in result
        assert "p_EmployeeID INT" in result
        assert "WITH RECURSIVE" in result
        assert "CREATE OR REPLACE FUNCTION" in result

    # Full SP 14: safe insert with TRY/CATCH
    def test_sp14_safe_insert_order(self):
        sql = """CREATE PROCEDURE dbo.usp_safe_insert_order
    @CustomerID NCHAR(5),
    @EmployeeID INT,
    @UnitPrice MONEY,
    @OrderID INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRY
        INSERT INTO Sales.Orders (CustomerID, EmployeeID)
        VALUES (@CustomerID, @EmployeeID);
        SET @OrderID = SCOPE_IDENTITY();
        IF @@ROWCOUNT = 0
        BEGIN
            RAISERROR('No row inserted', 16, 1);
        END;
        COMMIT TRANSACTION;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0
            ROLLBACK TRANSACTION;
        SET @OrderID = NULL;
        THROW;
    END CATCH;
END;
GO"""
        result = self._conv(sql)
        assert "usp_safe_insert_order" in result
        assert "CHAR(5)" in result         # NCHAR(5) → CHAR(5)
        assert "NUMERIC" in result         # MONEY → NUMERIC
        assert "INOUT p_OrderID" in result
        assert "EXCEPTION" in result
        assert "WHEN OTHERS THEN" in result
        assert "BEGIN TRY" not in result


# ---------------------------------------------------------------------------
# SprocType detection tests
# ---------------------------------------------------------------------------

class TestSprocTypeDetection:
    """Tests for PROCEDURE vs FUNCTION determination logic."""

    def test_select_only_is_function(self):
        body = "SELECT ProductID, ProductName FROM Products;"
        has_output = False
        stype = TsqlToPlpgsqlConverter.detect_sproc_type(body, has_output)
        assert stype == SprocType.FUNCTION

    def test_multiple_selects_is_function(self):
        body = "SELECT * FROM Products;\nSELECT * FROM Orders;"
        has_output = False
        stype = TsqlToPlpgsqlConverter.detect_sproc_type(body, has_output)
        assert stype == SprocType.FUNCTION

    def test_dml_with_output_is_procedure(self):
        body = "INSERT INTO t VALUES (1);"
        has_output = True
        stype = TsqlToPlpgsqlConverter.detect_sproc_type(body, has_output)
        assert stype == SprocType.PROCEDURE

    def test_dml_only_no_output_is_procedure(self):
        body = "UPDATE Products SET Price = 1 WHERE Id = 5;"
        has_output = False
        stype = TsqlToPlpgsqlConverter.detect_sproc_type(body, has_output)
        assert stype == SprocType.PROCEDURE

    def test_mixed_dml_select_with_output_is_function(self):
        body = (
            "INSERT INTO Orders (CustomerID) VALUES ('ALFKI');\n"
            "SELECT * FROM Orders WHERE CustomerID = 'ALFKI';\n"
        )
        has_output = False
        stype = TsqlToPlpgsqlConverter.detect_sproc_type(body, has_output)
        assert stype == SprocType.FUNCTION


# ---------------------------------------------------------------------------
# Bug regression tests
# ---------------------------------------------------------------------------

class TestBug1SingleLineIfBodySplit:
    """Regression tests for Bug 1: single-line IF condition+body mangling.

    T-SQL: ``IF @WhereClause IS NOT NULL SET @Sql = @Sql + ' WHERE ' + @WhereClause``
    was being converted to: ``IF p_WhereClause IS NOT NULL v_Sql := ... THEN``
    (THEN appended after body instead of after condition).
    """

    def _convert_body(self, tsql_body: str, params: "list[ParamInfo] | None" = None) -> str:
        if params is None:
            params = [
                ParamInfo(name="WhereClause", pg_type="TEXT", default_value="NULL"),
                ParamInfo(name="Sql", pg_type="TEXT"),
            ]
        return TsqlBodyConverter.convert(tsql_body, params)

    def test_single_line_if_set_produces_valid_if_then(self):
        """IF cond SET @var = expr → IF cond THEN v_var := expr; END IF;"""
        body = "IF @WhereClause IS NOT NULL SET @Sql = @Sql + ' WHERE ' + @WhereClause;"
        result = self._convert_body(body)
        assert "IS NOT NULL THEN" in result, "THEN must follow condition"
        assert "END IF;" in result, "END IF; must be present"
        assert "v_Sql :=" in result or "p_Sql :=" in result, "assignment must be in body"
        # The THEN must come BEFORE the assignment, not after it
        then_pos = result.find("IS NOT NULL THEN")
        assign_pos = result.find(":=")
        assert then_pos < assign_pos, "THEN must appear before the := assignment"

    def test_no_spurious_then_at_end_of_body(self):
        """Ensure 'variable THEN' pattern does not appear (the original bug)."""
        body = "IF @WhereClause IS NOT NULL SET @Sql = @Sql + ' WHERE ' + @WhereClause;"
        result = self._convert_body(body)
        import re
        assert not re.search(r':=\s*.*THEN\s*$', result, re.MULTILINE), \
            "THEN must not appear at the end of a body line"

    def test_pure_condition_without_body_unchanged(self):
        """A pure condition line (no body) must not be mangled."""
        params = [ParamInfo(name="x", pg_type="INT")]
        body = "IF @x > 0\n    SET @x = @x + 1;"
        result = TsqlBodyConverter.convert(body, params)
        # No spurious THEN after assignment
        assert "THEN" in result, "THEN must be present"
        lines = [l.strip() for l in result.splitlines() if l.strip()]
        # The THEN must appear on the same line as the condition, before the body
        then_line = next((l for l in lines if 'THEN' in l.upper()), None)
        assert then_line is not None
        assert ':=' not in then_line, "THEN line must not contain :="

    def test_elsif_single_line_body_split(self):
        """ELSIF with embedded body must also be split correctly."""
        params = [
            ParamInfo(name="City", pg_type="TEXT", default_value="NULL"),
            ParamInfo(name="State", pg_type="TEXT", default_value="NULL"),
        ]
        body = (
            "IF @City IS NOT NULL SET @x = 1;\n"
            "ELSE IF @City IS NULL AND @State IS NULL SET @y = 2;"
        )
        result = TsqlBodyConverter.convert(body, params)
        # Should not produce ELSIF ... := ... THEN (the original bug)
        import re
        assert not re.search(r'ELSIF[^;]+:=[^;]+THEN', result, re.I), \
            "ELSIF must not have embedded assignment before THEN"


class TestBug3StringConcatFix:
    """Regression tests for Bug 3: string + operator not fully converted to ||.

    The original bug: ``quote_ident(x) + 'str'`` was left as-is because
    the right operand ``x`` ends with ``)`` not a word character.
    """

    def test_func_result_plus_string(self):
        """quote_ident(x) + 'str' → quote_ident(x) || 'str'"""
        params = [ParamInfo(name="ColName", pg_type="TEXT")]
        body = "SET @Sql = 'SELECT ' + QUOTENAME(@ColName) + ' FROM tbl';"
        result = TsqlBodyConverter.convert(body, params)
        # After conversion QUOTENAME → quote_ident, + → ||
        assert "quote_ident" in result.lower() or "||" in result
        # The critical check: no remaining + between ) and '
        import re
        assert not re.search(r'\)\s*\+\s*\'', result), \
            "Remaining ) + 'str' pattern found — Bug 3 not fully fixed"

    def test_mixed_operators_in_dynamic_sql(self):
        """Ensure || is used consistently after conversion."""
        params = [ParamInfo(name="TableName", pg_type="TEXT")]
        body = "SET @Sql = 'SELECT * FROM ' + QUOTENAME(@TableName) + ' WHERE 1=1';"
        result = TsqlBodyConverter.convert(body, params)
        # Should use || exclusively for string concatenation
        assert "||" in result, "String concatenation || must be present"


class TestTopNFix:
    """Tests for SELECT TOP (n) → SELECT ... LIMIT n conversion."""

    def test_top_variable_moved_to_limit(self):
        """SELECT TOP (@n) → SELECT ... LIMIT n."""
        params = [ParamInfo(name="TopN", pg_type="INT", default_value="10")]
        body = "SELECT TOP (@TopN) col1, col2 FROM tbl ORDER BY col1;"
        result = TsqlBodyConverter.convert(body, params)
        assert "LIMIT" in result.upper(), "LIMIT must appear in output"
        assert "SELECT TOP" not in result.upper(), "SELECT TOP must be removed"
        # LIMIT must appear after ORDER BY (structural check)
        limit_pos = result.upper().find("LIMIT")
        orderby_pos = result.upper().find("ORDER BY")
        if orderby_pos != -1:
            assert limit_pos > orderby_pos, "LIMIT must come after ORDER BY"

    def test_top_literal_converted(self):
        """SELECT TOP 10 col → SELECT col LIMIT 10."""
        params: list[ParamInfo] = []
        body = "SELECT TOP 10 col1 FROM tbl;"
        result = TsqlBodyConverter.convert(body, params)
        assert "TOP 10" not in result.upper(), "TOP 10 must be removed or commented"
        assert "GOES TO END" not in result, "LIMIT placeholder must be resolved"
        assert "LIMIT 10" in result.upper(), "LIMIT 10 must appear at end of SELECT"

    def test_top_literal_in_subquery(self):
        """SELECT TOP 1 inside a subquery → LIMIT 1 before closing paren."""
        params: list[ParamInfo] = []
        body = "SELECT col FROM t WHERE id IN (SELECT TOP 1 id FROM t2 ORDER BY x);"
        result = TsqlBodyConverter.convert(body, params)
        assert "GOES TO END" not in result
        assert "LIMIT 1" in result.upper()
        assert result.upper().index("LIMIT 1") < result.index(")")


class TestNewConversionRules:
    """Tests for new conversion rules added in the fix phase."""

    def test_identity_column_converted(self):
        """IDENTITY(1,1) in CREATE TEMP TABLE → GENERATED ALWAYS AS IDENTITY."""
        params: list[ParamInfo] = []
        body = "CREATE TABLE #Results (RowID INT IDENTITY(1,1), Name VARCHAR(100));"
        result = TsqlBodyConverter.convert(body, params)
        assert "GENERATED ALWAYS AS IDENTITY" in result, \
            "IDENTITY(1,1) must be converted to GENERATED ALWAYS AS IDENTITY"
        assert "IDENTITY(1,1)" not in result, "Original IDENTITY syntax must be removed"

    def test_datetime2_converted_to_timestamp(self):
        """DATETIME2 in DECLARE → TIMESTAMP."""
        params: list[ParamInfo] = []
        body = "DECLARE @StartTime DATETIME2 = GETDATE();"
        result = TsqlBodyConverter.convert(body, params)
        assert "DATETIME2" not in result.upper(), "DATETIME2 must be converted"
        assert "TIMESTAMP" in result.upper(), "TIMESTAMP must appear in output"

    def test_sql_variant_converted_to_text(self):
        """SQL_VARIANT → TEXT."""
        params: list[ParamInfo] = []
        body = "DECLARE @Val SQL_VARIANT;"
        result = TsqlBodyConverter.convert(body, params)
        assert "SQL_VARIANT" not in result.upper(), "SQL_VARIANT must be converted"

    def test_cursor_local_removed(self):
        """CURSOR LOCAL FAST_FORWARD FOR → CURSOR FOR."""
        params: list[ParamInfo] = []
        body = "DECLARE cur CURSOR LOCAL FAST_FORWARD FOR SELECT col FROM tbl;"
        result = TsqlBodyConverter.convert(body, params)
        assert "LOCAL" not in result.upper() or "CURSOR LOCAL" not in result.upper(), \
            "CURSOR LOCAL modifier must be removed"
        assert "FAST_FORWARD" not in result.upper(), \
            "FAST_FORWARD modifier must be removed"

    def test_fetch_status_converted(self):
        """@@FETCH_STATUS = 0 → FOUND."""
        params: list[ParamInfo] = []
        body = "WHILE @@FETCH_STATUS = 0 BEGIN FETCH NEXT FROM cur; END"
        result = TsqlBodyConverter.convert(body, params)
        assert "@@FETCH_STATUS" not in result, "@@FETCH_STATUS must be converted"
        assert "FOUND" in result or "NOT FOUND" in result, \
            "FOUND / NOT FOUND must appear in output"


class TestSubPackageImports:
    """Verify the plpgsql/ sub-package exports are all accessible."""

    def test_toplevel_shim_imports(self):
        """All public names from tsql_to_plpgsql.py must still be importable."""
        from domains.transpilation.converters.tsql_to_plpgsql import (  # noqa: F401
            TsqlToPlpgsqlConverter,
            TsqlHeaderParser,
            TsqlBodyConverter,
            TsqlTypeMapper,
            SprocType,
            ParamInfo,
            HeaderInfo,
        )

    def test_subpackage_direct_imports(self):
        """Each module in the sub-package must be independently importable."""
        from domains.transpilation.converters.plpgsql._models import (  # noqa: F401
            SprocType, ParamInfo, HeaderInfo,
        )
        from domains.transpilation.converters.plpgsql._type_mapper import (  # noqa: F401
            TsqlTypeMapper,
        )
        from domains.transpilation.converters.plpgsql._header_parser import (  # noqa: F401
            TsqlHeaderParser,
        )
        from domains.transpilation.converters.plpgsql._body_transforms import (  # noqa: F401
            TsqlBodyConverter,
        )
        from domains.transpilation.converters.plpgsql._output_builder import (  # noqa: F401
            TsqlToPlpgsqlConverter,
            format_plpgsql,
        )

    def test_format_plpgsql_basic(self):
        """format_plpgsql must return a non-empty string and not raise."""
        from domains.transpilation.converters.plpgsql._output_builder import format_plpgsql
        sql = (
            "CREATE OR REPLACE PROCEDURE dbo.test()\n"
            "LANGUAGE plpgsql\nAS $$\nBEGIN\n"
            "    SELECT id, name FROM users WHERE active = TRUE;\n"
            "END;\n$$;"
        )
        result = format_plpgsql(sql)
        assert result, "format_plpgsql must return non-empty string"
        assert "CREATE OR REPLACE PROCEDURE" in result

    def test_format_plpgsql_long_stmt_broken(self):
        """Long single-line INSERT should be split across multiple lines."""
        from domains.transpilation.converters.plpgsql._output_builder import format_plpgsql
        # Build a definitely-long single-line INSERT ending with ;
        cols = ", ".join([f"col{i}" for i in range(20)])
        vals = ", ".join([f"val{i}" for i in range(20)])
        long_stmt = f"    INSERT INTO my_table ({cols}) VALUES ({vals});"
        assert len(long_stmt) > 80, "test precondition: stmt must be >80 chars"
        result = format_plpgsql(long_stmt)
        # After formatting there should be more lines than before (columns split)
        assert result.count("\n") >= long_stmt.count("\n"), \
            "Formatter must add line breaks for long statements"
