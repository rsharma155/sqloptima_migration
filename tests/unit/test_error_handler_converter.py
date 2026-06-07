"""
Module: tests/unit/test_error_handler_converter.py
Purpose: Unit tests for ErrorHandlerConverter — TRY/CATCH error function mapping.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import pytest

from domains.transpilation.converters.error_handler_converter import ErrorHandlerConverter


class TestErrorHandlerConverter:
    """Test T-SQL error function conversion to PL/pgSQL equivalents."""

    def test_convert_error_message_to_sqlerrm(self) -> None:
        """Verify ERROR_MESSAGE() converted to SQLERRM."""
        sql = """
WHEN OTHERS THEN
    v_msg := ERROR_MESSAGE();
"""
        converted, count = ErrorHandlerConverter.convert_error_functions(sql)
        assert count > 0
        assert 'SQLERRM' in converted
        assert 'ERROR_MESSAGE' not in converted

    def test_convert_error_number_to_sqlstate(self) -> None:
        """Verify ERROR_NUMBER() converted to SQLSTATE."""
        sql = """
WHEN OTHERS THEN
    v_code := ERROR_NUMBER();
"""
        converted, count = ErrorHandlerConverter.convert_error_functions(sql)
        assert count > 0
        assert 'SQLSTATE' in converted
        assert 'ERROR_NUMBER' not in converted

    def test_convert_error_state(self) -> None:
        """Verify ERROR_STATE() converted to SQLSTATE."""
        sql = """
v_state := ERROR_STATE();
"""
        converted, count = ErrorHandlerConverter.convert_error_functions(sql)
        assert count > 0
        assert 'SQLSTATE' in converted

    def test_unsupported_error_severity_gets_comment(self) -> None:
        """Verify ERROR_SEVERITY() flagged for manual review."""
        sql = """
WHEN OTHERS THEN
    v_sev := ERROR_SEVERITY();
"""
        result = ErrorHandlerConverter.apply_all(sql)
        assert len(result.warnings) > 0 or '/*' in result.sql or '--' in result.sql

    def test_unsupported_error_line_gets_comment(self) -> None:
        """Verify ERROR_LINE() flagged for manual review."""
        sql = """
v_line := ERROR_LINE();
"""
        result = ErrorHandlerConverter.apply_all(sql)
        # Should have a warning or a comment
        assert len(result.warnings) > 0 or 'MANUAL REVIEW' in result.sql.upper()

    def test_multiple_error_functions_in_catch(self) -> None:
        """Verify multiple error functions in same CATCH block converted."""
        sql = """
WHEN OTHERS THEN
    v_msg := ERROR_MESSAGE();
    v_code := ERROR_NUMBER();
    v_state := ERROR_STATE();
"""
        result = ErrorHandlerConverter.apply_all(sql)
        assert result.fixes_applied >= 3
        assert 'SQLERRM' in result.sql
        assert 'ERROR_MESSAGE' not in result.sql

    def test_no_error_functions_no_changes(self) -> None:
        """Verify no changes when no error functions present."""
        sql = """
SELECT * FROM Products;
"""
        result = ErrorHandlerConverter.apply_all(sql)
        assert result.fixes_applied == 0
        assert result.sql == sql
