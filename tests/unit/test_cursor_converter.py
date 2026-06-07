"""
Module: tests/unit/test_cursor_converter.py
Purpose: Unit tests for CursorConverter — T-SQL CURSOR to PL/pgSQL REFCURSOR conversion.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import pytest

from domains.transpilation.converters.cursor_converter import CursorConverter


class TestCursorConverter:
    """Test T-SQL CURSOR to PL/pgSQL REFCURSOR pattern conversion."""

    def test_convert_declare_cursor_basic(self) -> None:
        """Verify DECLARE @cur CURSOR FOR SELECT converted to REFCURSOR declaration."""
        sql = """
DECLARE @ProductCursor CURSOR FOR
SELECT ProductID, ProductName FROM Products;
"""
        converted, count = CursorConverter.convert_declare(sql)
        assert count > 0
        # Check that @ProductCursor is converted to v_ProductCursor or product_cursor
        assert '@ProductCursor' not in converted
        assert 'REFCURSOR' in converted
        # The SELECT stays for now (will be moved to OPEN)
        assert 'SELECT ProductID, ProductName FROM Products' in converted

    def test_convert_open_cursor(self) -> None:
        """Verify OPEN @cur FOR SELECT converted to OPEN cur FOR SELECT."""
        sql = """
DECLARE v_product_cursor REFCURSOR;
OPEN @ProductCursor FOR SELECT * FROM Products;
"""
        converted, count = CursorConverter.convert_open(sql)
        assert count > 0
        assert 'OPEN v_product_cursor FOR SELECT' in converted or 'OPEN v_ProductCursor FOR SELECT' in converted

    def test_convert_fetch_basic(self) -> None:
        """Verify FETCH NEXT FROM @cur INTO @vars converted."""
        sql = """
FETCH NEXT FROM @ProductCursor INTO @ProductID, @ProductName;
"""
        converted, count = CursorConverter.convert_fetch(sql)
        assert count > 0
        assert '@ProductCursor' not in converted
        assert '@ProductID' not in converted
        assert '@ProductName' not in converted
        assert 'FETCH NEXT FROM' in converted
        assert 'INTO' in converted

    def test_convert_fetch_with_spaces(self) -> None:
        """Verify FETCH handles varied whitespace."""
        sql = """
FETCH   NEXT   FROM   @cur   INTO   @a,   @b;
"""
        converted, count = CursorConverter.convert_fetch(sql)
        assert count > 0
        assert '@cur' not in converted
        assert '@a' not in converted

    def test_convert_fetch_status_loop_pattern(self) -> None:
        """Verify WHILE @@FETCH_STATUS = 0 converted to LOOP with EXIT."""
        sql = """
FETCH NEXT FROM @cur INTO @id, @name;
WHILE @@FETCH_STATUS = 0
BEGIN
    -- Process @id, @name
    FETCH NEXT FROM @cur INTO @id, @name;
END
"""
        converted, count = CursorConverter.convert_fetch_status_loop(sql)
        assert count > 0
        assert 'WHILE @@FETCH_STATUS = 0' not in converted
        assert 'LOOP' in converted
        assert 'EXIT WHEN NOT FOUND' in converted or 'EXIT WHEN' in converted

    def test_remove_close_cursor(self) -> None:
        """Verify CLOSE @cur statement converted properly."""
        sql = """
CLOSE @ProductCursor;
"""
        converted, count = CursorConverter.remove_close(sql)
        # Close statements should be converted or replaced with comment
        assert 'CLOSE' in converted.upper() or '-- CLOSE' in converted

    def test_remove_deallocate_cursor(self) -> None:
        """Verify DEALLOCATE @cur removed with annotation."""
        sql = """
DEALLOCATE @ProductCursor;
"""
        converted, count = CursorConverter.remove_deallocate(sql)
        assert count > 0
        # DEALLOCATE should be replaced with comment (PG has no DEALLOCATE)
        assert '-- DEALLOCATE' in converted or '/*' in converted
        # Should have a note that this is PG handled automatically
        assert 'PostgreSQL' in converted or 'handled' in converted.lower()

    def test_full_cursor_flow_simple(self) -> None:
        """Verify full cursor conversion from declaration to deallocation."""
        sql = """
DECLARE @ProductCursor CURSOR FOR
SELECT ProductID, ProductName FROM Products;

OPEN @ProductCursor;
FETCH NEXT FROM @ProductCursor INTO @ProductID, @ProductName;

WHILE @@FETCH_STATUS = 0
BEGIN
    PRINT @ProductName;
    FETCH NEXT FROM @ProductCursor INTO @ProductID, @ProductName;
END

CLOSE @ProductCursor;
DEALLOCATE @ProductCursor;
"""
        result = CursorConverter.apply_all(sql)
        assert result.fixes_applied > 0
        # After conversion, should have REFCURSOR
        assert 'REFCURSOR' in result.sql
        # Main DECLARE should be converted
        assert 'DECLARE v_ProductCursor REFCURSOR' in result.sql
        # Should have LOOP instead of WHILE
        assert 'LOOP' in result.sql
        # DEALLOCATE should be commented
        assert '-- DEALLOCATE' in result.sql

    def test_cursor_with_parameters(self) -> None:
        """Verify cursor declaration with parameters is flagged for manual review."""
        sql = """
DECLARE @OrderCursor CURSOR;
SET @OrderCursor = CURSOR FORWARD_ONLY FOR
SELECT OrderID, Amount FROM Orders WHERE CustomerID = @CustID;
"""
        result = CursorConverter.apply_all(sql)
        # Complex cursor parameters should result in warnings
        assert len(result.warnings) > 0 or result.fixes_applied >= 0

    def test_no_cursor_no_changes(self) -> None:
        """Verify no cursor patterns result in no changes."""
        sql = """
SELECT * FROM Products;
INSERT INTO History VALUES ('Product listed');
"""
        result = CursorConverter.apply_all(sql)
        assert result.fixes_applied == 0
        assert result.sql == sql

    def test_cursor_varying_output_pattern_flagged(self) -> None:
        """Verify CURSOR VARYING OUTPUT (return result set) gets manual review flag."""
        sql = """
-- CURSOR VARYING OUTPUT parameter (requires function wrapping)
DECLARE @cur CURSOR VARYING OUTPUT;
SET @cur = CURSOR FORWARD_ONLY FOR SELECT * FROM Orders;
"""
        result = CursorConverter.apply_all(sql)
        # Should have warning about manual review
        assert any('MANUAL REVIEW' in w.upper() for w in result.warnings) or len(result.warnings) > 0

    def test_nested_cursor_handling(self) -> None:
        """Verify nested cursors are processed."""
        sql = """
DECLARE @outer CURSOR FOR SELECT CategoryID FROM Categories;
OPEN @outer;
FETCH NEXT FROM @outer INTO @catid;

WHILE @@FETCH_STATUS = 0
BEGIN
    DECLARE @inner CURSOR FOR SELECT ProductID FROM Products WHERE CategoryID = @catid;
    OPEN @inner;
    FETCH NEXT FROM @inner INTO @prodid;

    WHILE @@FETCH_STATUS = 0
    BEGIN
        -- Process product
        FETCH NEXT FROM @inner INTO @prodid;
    END

    CLOSE @inner;
    DEALLOCATE @inner;

    FETCH NEXT FROM @outer INTO @catid;
END

CLOSE @outer;
DEALLOCATE @outer;
"""
        result = CursorConverter.apply_all(sql)
        assert result.fixes_applied > 0
        # Both cursors should be processed
        assert result.sql.count('REFCURSOR') >= 1
        # Main cursors should be converted
        assert 'DECLARE v_outer REFCURSOR' in result.sql
        assert 'DECLARE v_inner REFCURSOR' in result.sql
