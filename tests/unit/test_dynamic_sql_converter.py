"""
Module: tests/unit/test_dynamic_sql_converter.py
Purpose: Unit tests for DynamicSqlConverter — sp_executesql and EXEC conversion.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import pytest

from domains.transpilation.converters.dynamic_sql_converter import DynamicSqlConverter


class TestDynamicSqlConverter:
    """Test sp_executesql and EXEC pattern conversion."""

    def test_exec_sp_executesql_with_params(self) -> None:
        """Verify EXEC sp_executesql with parameters converted to EXECUTE USING."""
        sql = """
EXEC sp_executesql @sql, N'@OrderID INT, @Status NVARCHAR(20)', @OrderID, @Status;
"""
        converted, count = DynamicSqlConverter.convert_sp_executesql(sql)
        assert count > 0
        assert 'EXECUTE' in converted
        assert 'USING' in converted
        assert 'v_OrderID' in converted
        assert 'v_Status' in converted

    def test_exec_sp_executesql_no_params(self) -> None:
        """Verify EXEC sp_executesql without parameters."""
        sql = """
EXEC sp_executesql @sql;
"""
        converted, count = DynamicSqlConverter.convert_sp_executesql(sql)
        assert count > 0
        assert 'EXECUTE' in converted

    def test_exec_variable_dynamic(self) -> None:
        """Verify EXEC (@sql) pattern converted."""
        sql = """
EXEC (@DynamicSQL);
"""
        converted, count = DynamicSqlConverter.convert_exec_variable(sql)
        assert count > 0
        assert 'EXECUTE' in converted

    def test_exec_static_proc_name(self) -> None:
        """Verify EXEC dbo.usp_something @param converted."""
        sql = """
EXEC dbo.usp_GetProducts @CategoryID;
"""
        converted, count = DynamicSqlConverter.convert_static_exec(sql)
        # Static EXEC should be converted to PERFORM or CALL
        assert 'PERFORM' in converted or 'CALL' in converted

    def test_no_exec_no_changes(self) -> None:
        """Verify no changes when no EXEC patterns present."""
        sql = """
SELECT * FROM Products;
"""
        result = DynamicSqlConverter.apply_all(sql)
        assert result.fixes_applied == 0
        assert result.sql == sql

    def test_exec_with_multiple_params(self) -> None:
        """Verify EXEC with multiple parameters handled."""
        sql = """
EXEC sp_executesql @sql,
    N'@ID INT, @Name NVARCHAR(100), @Active BIT',
    @ID, @Name, @Active;
"""
        result = DynamicSqlConverter.apply_all(sql)
        assert result.fixes_applied > 0
        assert result.sql.count('USING') >= 1

    def test_nested_exec_statements(self) -> None:
        """Verify nested EXEC statements handled."""
        sql = """
DECLARE @sql NVARCHAR(MAX) = 'EXEC sp_something';
EXEC sp_executesql @sql;
"""
        result = DynamicSqlConverter.apply_all(sql)
        assert result.fixes_applied >= 1
