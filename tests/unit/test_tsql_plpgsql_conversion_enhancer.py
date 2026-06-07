"""
Unit tests for T-SQL to PL/pgSQL conversion enhancer integration with ProceduralConverter

Tests verify that:
1. Phase 1 enhancements are applied (parameter fixes, variable prefixes)
2. Phase 2 enhancements are applied (hint removal, pattern flagging)
3. Phase 3 enhancements are applied (transaction control, syntax cleanup)
4. Integration doesn't break existing functionality

Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

import pytest
from domains.transpilation.procedural_converter import ProceduralConverter
from domains.transpilation.tsql_plpgsql_conversion_enhancer import (
    Phase1Enhancements,
    Phase2Enhancements,
    Phase3Enhancements,
    EnhancedProceduralConverter,
)
from application.conversion_service import ConversionService, ConversionRequest


class TestPhase1Enhancements:
    """Test Phase 1: Quick Wins"""

    def test_parameter_commas_fixed(self):
        """Verify duplicate commas in parameter lists are fixed"""
        enhancer = Phase1Enhancements()
        sql = """CREATE PROCEDURE test(
    @param1 INT DEFAULT NULL,,
    @param2 VARCHAR(50)
)"""
        result_sql, count = enhancer.fix_parameter_commas(sql)
        assert count == 1
        assert ",," not in result_sql
        assert "DEFAULT NULL," in result_sql

    def test_variable_prefixes_converted(self):
        """Verify @ prefix is converted to p_/v_"""
        enhancer = Phase1Enhancements()
        sql = """CREATE PROCEDURE test(
    IN p_param1 INT
)
BEGIN
    SET @var1 = @param1;
END"""
        result_sql, count = enhancer.fix_variable_prefixes(sql)
        assert count > 0
        assert "@var1" not in result_sql or "p_var1" in result_sql

    def test_scope_identity_mapped(self):
        """Verify SCOPE_IDENTITY() is converted to LASTVAL()"""
        enhancer = Phase1Enhancements()
        sql = "SET @id = SCOPE_IDENTITY();"
        result_sql, count = enhancer.fix_scope_identity(sql)
        assert count == 1
        assert "LASTVAL()" in result_sql
        assert "SCOPE_IDENTITY" not in result_sql


class TestPhase2Enhancements:
    """Test Phase 2: Medium Complexity"""

    def test_with_hints_removed(self):
        """Verify WITH hints are removed"""
        enhancer = Phase2Enhancements()
        sql = "SELECT * FROM table WITH (NOLOCK) WHERE id = 1"
        result_sql, count = enhancer.remove_with_hints(sql)
        assert count == 1
        assert "WITH (NOLOCK)" not in result_sql
        assert "SELECT * FROM table" in result_sql

    def test_option_hints_removed(self):
        """Verify OPTION clauses are removed"""
        enhancer = Phase2Enhancements()
        sql = "SELECT * FROM table OPTION (MAXDOP 4, RECOMPILE)"
        result_sql, count = enhancer.remove_option_hints(sql)
        assert count == 1
        assert "OPTION" not in result_sql

    def test_merge_flagged(self):
        """Verify MERGE statements are flagged"""
        enhancer = Phase2Enhancements()
        sql = "MERGE target USING source ON ..."
        result_sql, count = enhancer.flag_complex_patterns(sql)
        assert "-- CRITICAL: PostgreSQL does not support MERGE" in result_sql


class TestPhase3Enhancements:
    """Test Phase 3: Complex Patterns"""

    def test_transaction_control_converted(self):
        """Verify transaction statements are converted"""
        enhancer = Phase3Enhancements()
        sql = """BEGIN TRANSACTION;
        UPDATE table SET col = 1;
        COMMIT TRANSACTION;"""
        result_sql, count = enhancer.fix_transaction_control(sql)
        assert "BEGIN;" in result_sql
        assert "COMMIT;" in result_sql
        assert "TRANSACTION" not in result_sql

    def test_raiserror_converted(self):
        """Verify RAISERROR is converted to RAISE EXCEPTION"""
        enhancer = Phase3Enhancements()
        sql = "RAISERROR('Error message', 16, 1)"
        result_sql, count = enhancer.convert_error_handling(sql)
        assert count > 0
        assert "RAISE EXCEPTION 'Error message'" in result_sql
        assert "RAISERROR" not in result_sql

    def test_duplicates_removed(self):
        """Verify duplicate statements are removed"""
        enhancer = Phase3Enhancements()
        sql = """UPDATE table SET col = 1;
        UPDATE table SET col = 1;
        RAISE EXCEPTION 'test';
        RAISE EXCEPTION 'test';"""
        result_sql, count = enhancer.remove_duplicates(sql)
        assert count > 0
        # Verify duplicates reduced
        assert result_sql.count("UPDATE table") <= 1 or result_sql.count("UPDATE table") < 2

    def test_syntax_fixes_applied(self):
        """Verify syntax issues are fixed"""
        enhancer = Phase3Enhancements()
        sql = """IF @var = 0
        SELECT 'value'
        SET @result = 1"""
        result_sql, count = enhancer.fix_syntax_issues(sql)
        assert "THEN" in result_sql or count > 0


class TestEnhancedProceduralConverter:
    """Test integrated EnhancedProceduralConverter"""

    def test_all_phases_applied(self):
        """Verify all phases are applied in sequence"""
        converter = EnhancedProceduralConverter()
        sql = """CREATE PROCEDURE test(
    @param1 INT DEFAULT NULL,,
    @param2 VARCHAR(50),,
)
BEGIN
    BEGIN TRANSACTION;
    SET @var = SCOPE_IDENTITY();
    RAISERROR('test', 16, 1);
    COMMIT TRANSACTION;
    SELECT * FROM table WITH (NOLOCK);
END"""

        result = converter.apply_all_phases(sql)

        assert result.fixes_applied > 0
        assert ",," not in result.sql
        assert "SCOPE_IDENTITY" not in result.sql
        assert "WITH (NOLOCK)" not in result.sql
        assert "BEGIN;" in result.sql
        assert "COMMIT;" in result.sql


class TestProceduralConverterIntegration:
    """Test ProceduralConverter with phase enhancements enabled"""

    def test_converter_with_enhancements_enabled(self):
        """Verify ProceduralConverter applies phase enhancements"""
        converter = ProceduralConverter(enable_phase_enhancements=True)
        assert converter._enhanced_converter is not None

    def test_converter_with_enhancements_disabled(self):
        """Verify ProceduralConverter can disable phase enhancements"""
        converter = ProceduralConverter(enable_phase_enhancements=False)
        assert converter._enhanced_converter is None

    def test_simple_procedure_conversion(self):
        """A SELECT-only CREATE PROCEDURE converts to a PL/pgSQL FUNCTION.

        CAT-2 fix: a stored procedure whose body only performs SELECTs and has
        no OUTPUT parameters is correctly converted to a FUNCTION (not PROCEDURE)
        in PostgreSQL.  The name, parameters, and dollar-quote delimiter are
        preserved correctly.
        """
        converter = ProceduralConverter(enable_phase_enhancements=True)

        tsql = """CREATE PROCEDURE dbo.sp_test
            @ProductID INT,
            @Name NVARCHAR(100)
        AS
        BEGIN
            SELECT @ProductID;
        END"""

        result = converter.auto_convert(tsql)

        assert result.success
        # SELECT-only SP → FUNCTION (CAT-2 correct behavior)
        assert "CREATE OR REPLACE FUNCTION" in result.converted_sql
        assert "sp_test" in result.converted_sql
        # Parameters should be present with p_ prefix
        assert "p_ProductID" in result.converted_sql
        assert "p_Name" in result.converted_sql
        # Dollar-quote delimiter must be $$, not $function$
        assert "$$" in result.converted_sql
        # Malformed double-comma artifacts must never survive a conversion.
        assert ",," not in result.converted_sql


class TestConversionServiceIntegration:
    """Test ConversionService with phase enhancements"""

    def test_service_applies_enhancements_by_default(self):
        """Verify ConversionService applies enhancements by default"""
        service = ConversionService(enable_phase_enhancements=True)
        assert service._converter._enhanced_converter is not None

    def test_service_can_disable_enhancements(self):
        """Verify ConversionService can disable enhancements if needed"""
        service = ConversionService(enable_phase_enhancements=False)
        assert service._converter._enhanced_converter is None

    def test_service_surfaces_enhancement_warnings(self):
        """ConversionService surfaces enhancement warnings for patterns that
        need manual review — e.g. a NOLOCK hint, which is removed and flagged."""
        service = ConversionService(enable_phase_enhancements=True)

        request = ConversionRequest(
            sql="SELECT * FROM Products WITH (NOLOCK);",
            object_type="auto",
            schema="dbo",
            name="q",
        )

        result = service.convert(request)

        assert result.success
        assert len(result.warnings) > 0
        assert any("NOLOCK" in w for w in result.warnings)
        # The hint must be stripped from the emitted SQL.
        assert "WITH (NOLOCK)" not in result.converted_sql


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
