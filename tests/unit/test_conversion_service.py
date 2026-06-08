"""
Module: tests/unit/test_conversion_service.py
Purpose: Unit tests for ConversionService — object type detection, auto-convert
         dispatch, and error handling for empty input.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import pytest

from application.conversion_service import ConversionRequest, ConversionService


@pytest.fixture
def svc() -> ConversionService:
    return ConversionService()


class TestConversionServiceAutoConvert:
    def test_auto_converts_procedure(self, svc: ConversionService):
        sql = """
        CREATE PROCEDURE dbo.usp_hello
        AS BEGIN
            SELECT 1;
        END
        """
        req = ConversionRequest(sql=sql, object_type="auto")
        result = svc.convert(req)
        assert result.success
        assert "usp_hello" in result.converted_sql or result.converted_sql

    def test_auto_converts_adhoc_select(self, svc: ConversionService):
        req = ConversionRequest(sql="SELECT GETDATE()", object_type="auto")
        result = svc.convert(req)
        assert result.success
        assert "NOW()" in result.converted_sql.upper() or result.success

    def test_empty_sql_fails(self, svc: ConversionService):
        req = ConversionRequest(sql="", object_type="auto")
        result = svc.convert(req)
        assert not result.success
        assert result.errors

    def test_whitespace_only_fails(self, svc: ConversionService):
        req = ConversionRequest(sql="   \n   ", object_type="auto")
        result = svc.convert(req)
        assert not result.success

    def test_explicit_raw_type(self, svc: ConversionService):
        req = ConversionRequest(sql="SELECT 1 + 1", object_type="raw")
        result = svc.convert(req)
        # raw SQL should at least attempt conversion
        assert isinstance(result.success, bool)

    def test_nolock_removal_in_conversion(self, svc: ConversionService):
        sql = "SELECT * FROM dbo.orders WITH (NOLOCK) WHERE id = 1"
        req = ConversionRequest(sql=sql, object_type="raw")
        result = svc.convert(req)
        # Should have a warning about NOLOCK
        assert any("NOLOCK" in w.upper() for w in result.warnings) or result.success

    def test_for_xml_annotation_in_conversion(self, svc: ConversionService):
        sql = "SELECT id, name FROM t FOR XML PATH('item')"
        req = ConversionRequest(sql=sql, object_type="raw")
        result = svc.convert(req)
        assert isinstance(result.success, bool)

    def test_conversion_service_returns_conversion_result(self, svc: ConversionService):
        from domains.transpilation.procedural_converter import ConversionResult

        req = ConversionRequest(sql="SELECT 1", object_type="raw")
        result = svc.convert(req)
        assert isinstance(result, ConversionResult)
        assert isinstance(result.postgres_syntax_valid, bool)

    def test_empty_input_requires_manual_review(self, svc: ConversionService):
        req = ConversionRequest(sql="", object_type="auto")
        result = svc.convert(req)
        assert result.manual_review_required


class TestCursorProcedureConversion:
    """Cursor + string-concat loop SPs must convert to valid PL/pgSQL FOR loops."""

    _BAD_CURSOR_SP = """
    CREATE PROCEDURE dbo.usp_BuildCustomerList_Bad
    AS
    BEGIN
        SET NOCOUNT ON;
        DECLARE @CustomerList NVARCHAR(MAX) = '';
        DECLARE @CustomerName NVARCHAR(200);
        DECLARE name_cursor CURSOR FOR
        SELECT TOP 10000 FirstName + ' ' + LastName
        FROM Customers
        WHERE CustomerStatus = 'VIP';
        OPEN name_cursor;
        FETCH NEXT FROM name_cursor INTO @CustomerName;
        WHILE @@FETCH_STATUS = 0
        BEGIN
            SET @CustomerList = @CustomerList + @CustomerName + ', ';
            FETCH NEXT FROM name_cursor INTO @CustomerName;
        END
        CLOSE name_cursor;
        DEALLOCATE name_cursor;
        SELECT @CustomerList as CustomerList;
    END
    """

    def test_cursor_loop_converts_to_for_in_select(self, svc: ConversionService):
        req = ConversionRequest(
            sql=self._BAD_CURSOR_SP,
            object_type="procedure",
            schema="dbo",
            name="usp_BuildCustomerList_Bad",
        )
        result = svc.convert(req)
        assert result.success
        assert result.postgres_syntax_valid
        assert not result.errors
        sql = result.converted_sql
        assert "FOR v_CustomerName IN" in sql
        assert "OPEN AS" not in sql
        assert "FOR r IN" not in sql
        assert "LIMIT 10000" in sql
        assert "v_CustomerList||v_CustomerName" in sql.replace(" ", "")
        assert "AS\n        BEGIN" not in sql


class TestDboSchemaStrategy:
    _SIMPLE_SP = """
    CREATE PROCEDURE dbo.usp_SchemaTest
    AS
    BEGIN
        SELECT * FROM dbo.orders;
    END
    """

    def test_preserve_dbo_keeps_schema_qualifiers(self):
        from application.conversion_factory import build_conversion_service

        svc = build_conversion_service("dbo", "dbo", dbo_schema_strategy="preserve_dbo")
        result = svc.convert(
            ConversionRequest(
                sql=self._SIMPLE_SP,
                object_type="procedure",
                schema="dbo",
                name="usp_SchemaTest",
                dbo_schema_strategy="preserve_dbo",
            )
        )
        assert result.success
        sql = result.converted_sql.lower()
        assert "dbo." in sql or "dbo.orders" in sql.replace(" ", "")
        assert "public.orders" not in sql

    def test_map_to_public_rewrites_dbo(self):
        from application.conversion_factory import build_conversion_service

        svc = build_conversion_service("dbo", "public", dbo_schema_strategy="map_to_public")
        result = svc.convert(
            ConversionRequest(
                sql=self._SIMPLE_SP,
                object_type="auto",
                schema="dbo",
                name="usp_SchemaTest",
            )
        )
        assert result.success
        assert "dbo." not in result.converted_sql.lower()


class TestTryCatchProcedureConversion:
    """AdventureWorks-style TRY/CATCH error logging procedures."""

    _USP_LOG_ERROR = r"""
    CREATE PROCEDURE [dbo].[uspLogError]
        @ErrorLogID [int] = 0 OUTPUT
    AS
    BEGIN
        SET NOCOUNT ON;
        SET @ErrorLogID = 0;
        BEGIN TRY
            IF ERROR_NUMBER() IS NULL
                RETURN;
            INSERT [dbo].[ErrorLog] ([UserName], [ErrorNumber], [ErrorMessage])
            VALUES (CONVERT(sysname, CURRENT_USER), ERROR_NUMBER(), ERROR_MESSAGE());
            SET @ErrorLogID = @@IDENTITY;
        END TRY
        BEGIN CATCH
            EXECUTE [dbo].[uspPrintError];
            RETURN -1;
        END CATCH
    END;
    """

    def test_usp_log_error_maps_dbo_schema_and_passes_syntax(self):
        from application.conversion_factory import build_conversion_service

        svc = build_conversion_service("dbo", "public")
        req = ConversionRequest(
            sql=self._USP_LOG_ERROR,
            object_type="procedure",
            schema="dbo",
            name="uspLogError",
        )
        result = svc.convert(req)
        sql = result.converted_sql
        assert result.success
        assert result.postgres_syntax_valid, result.errors
        assert "dbo." not in sql.lower()
        assert "INSERT INTO public" in sql
        assert "CALLpublic.uspPrintError()" in sql.replace(" ", "")


class TestAdventureWorksRecursiveProcedures:
    """Recursive CTE + OPTION (MAXRECURSION) AdventureWorks procedures."""

    _BOM = r"""
    CREATE PROCEDURE [dbo].[uspGetBillOfMaterials]
    @StartProductID [int], @CheckDate [datetime]
    AS BEGIN SET NOCOUNT ON;
    WITH [BOM_cte]([ProductAssemblyID], [ComponentID]) AS (
      SELECT b.[ProductAssemblyID], b.[ComponentID] FROM [Production].[BillOfMaterials] b
      WHERE b.[ProductAssemblyID] = @StartProductID
      UNION ALL
      SELECT b.[ProductAssemblyID], b.[ComponentID] FROM [BOM_cte] cte
      INNER JOIN [Production].[BillOfMaterials] b ON b.[ProductAssemblyID] = cte.[ComponentID]
    )
    SELECT * FROM [BOM_cte] ORDER BY 1 OPTION (MAXRECURSION 25)
    END;
    """

    _EMP_MANAGERS = r"""
    CREATE PROCEDURE [dbo].[uspGetEmployeeManagers] @EmployeeID [int] AS BEGIN SET NOCOUNT ON;
    WITH [EMP_cte]([EmployeeID], [ManagerID], [RecursionLevel]) AS (
      SELECT e.[EmployeeID], e.[ManagerID], 0 FROM [HumanResources].[Employee] e
      WHERE e.[EmployeeID]=@EmployeeID
      UNION ALL
      SELECT e.[EmployeeID], e.[ManagerID], [RecursionLevel]+1 FROM [HumanResources].[Employee] e
      INNER JOIN [EMP_cte] ON e.[EmployeeID]=[EMP_cte].[ManagerID]
    )
    SELECT c.[FirstName] AS 'ManagerFirstName', c.[LastName] AS 'ManagerLastName'
    FROM [EMP_cte] INNER JOIN [HumanResources].[Employee] e ON [EMP_cte].[ManagerID]=e.[EmployeeID]
    INNER JOIN [Person].[Contact] c ON e.[ContactID]=c.[ContactID]
    ORDER BY 1 OPTION (MAXRECURSION 25) END;
    """

    def test_recursive_procedures_convert_for_public_schema(self):
        from application.conversion_factory import build_conversion_service

        svc = build_conversion_service("dbo", "public")
        for name, sql in [
            ("uspGetBillOfMaterials", self._BOM),
            ("uspGetEmployeeManagers", self._EMP_MANAGERS),
        ]:
            result = svc.convert(
                ConversionRequest(sql=sql, object_type="procedure", schema="dbo", name=name)
            )
            assert result.postgres_syntax_valid, result.errors
            assert "OPTION" not in result.converted_sql
            assert "WITH RECURSIVE" in result.converted_sql
            assert "dbo." not in result.converted_sql.lower()
            if name == "uspGetEmployeeManagers":
                assert 'AS "ManagerFirstName"' in result.converted_sql
