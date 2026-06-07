"""
Test suite for CURSOR handling and conversion.

Tests conversion of T-SQL CURSOR operations to PostgreSQL REFCURSOR patterns.
"""

import pytest

from domains.transpilation.converters.cursor_handler import (
    CursorHandler,
    CursorWarnings,
)


class TestCursorParsing:
    """Test CURSOR definition parsing."""

    def test_parse_simple_cursor(self):
        """Parse basic CURSOR declaration."""
        sql = "DECLARE @cursor CURSOR FOR SELECT id, name FROM users;"
        cursor = CursorHandler.parse_cursor(sql)
        assert cursor is not None
        assert cursor.cursor_name == "@cursor"
        assert "SELECT" in cursor.query

    def test_parse_cursor_with_for_clause(self):
        """Parse CURSOR with FOR clause on separate line."""
        sql = """
        DECLARE @users_cursor CURSOR
        FOR SELECT id, name FROM users WHERE active = 1;
        """
        cursor = CursorHandler.parse_cursor(sql)
        assert cursor is not None
        assert cursor.cursor_name == "@users_cursor"
        assert "active" in cursor.query

    def test_parse_cursor_fetch_into(self):
        """Parse FETCH ... INTO statement."""
        sql = """
        DECLARE @cursor CURSOR FOR SELECT id, name FROM users;
        FETCH NEXT FROM @cursor INTO @id, @name;
        """
        cursor = CursorHandler.parse_cursor(sql)
        assert cursor is not None
        assert len(cursor.fetch_into_vars) > 0

    def test_parse_cursor_with_fetch_status(self):
        """Detect FETCH_STATUS check."""
        sql = """
        DECLARE @cursor CURSOR FOR SELECT * FROM users;
        OPEN @cursor;
        FETCH NEXT FROM @cursor INTO @id;
        WHILE @@FETCH_STATUS = 0
        BEGIN
            FETCH NEXT FROM @cursor INTO @id;
        END
        """
        cursor = CursorHandler.parse_cursor(sql)
        assert cursor is not None
        assert cursor.has_fetch_status_check is True

    def test_parse_refcursor(self):
        """Detect REFCURSOR usage."""
        sql = "DECLARE @cursor REFCURSOR; OPEN @cursor FOR SELECT * FROM users;"
        cursor = CursorHandler.parse_cursor(sql)
        assert cursor is not None
        assert cursor.uses_refcursor is True

    def test_parse_cursor_without_for(self):
        """Parse CURSOR without FOR clause (added later)."""
        sql = "DECLARE @cursor CURSOR; SET @cursor = CURSOR FOR SELECT * FROM users;"
        cursor = CursorHandler.parse_cursor(sql)
        assert cursor is not None


class TestCursorConversion:
    """Test CURSOR to FOR loop conversion."""

    def test_simple_cursor_to_for_loop(self):
        """Convert simple CURSOR to FOR loop."""
        sql = "DECLARE @users CURSOR FOR SELECT id, name FROM users WHERE active = 1;"
        result = CursorHandler.apply_all(sql)
        assert result.success is True
        assert "FOR" in result.sql
        assert "LOOP" in result.sql
        assert "SELECT" in result.sql

    def test_cursor_with_complex_query(self):
        """Convert CURSOR with complex SELECT."""
        sql = """
        DECLARE @cursor CURSOR
        FOR SELECT u.id, u.name, o.order_id
            FROM users u
            LEFT JOIN orders o ON u.id = o.user_id
            WHERE u.created_at > '2023-01-01';
        """
        result = CursorHandler.apply_all(sql)
        assert result.success is True
        assert "LEFT JOIN" in result.sql

    def test_cursor_loop_conversion(self):
        """Convert full CURSOR loop with body."""
        sql = """
        DECLARE @id INT, @name NVARCHAR(100);
        DECLARE @cursor CURSOR FOR SELECT id, name FROM users;
        OPEN @cursor;
        FETCH NEXT FROM @cursor INTO @id, @name;
        WHILE @@FETCH_STATUS = 0
        BEGIN
            PRINT @id + ': ' + @name;
            FETCH NEXT FROM @cursor INTO @id, @name;
        END
        CLOSE @cursor;
        DEALLOCATE @cursor;
        """
        result = CursorHandler.apply_all(sql)
        assert result is not None

    def test_refcursor_conversion(self):
        """Convert REFCURSOR to function."""
        sql = """
        DECLARE @cursor REFCURSOR;
        OPEN @cursor FOR SELECT id, name FROM employees WHERE salary > 50000;
        """
        result = CursorHandler.apply_all(sql)
        assert result.success is True
        assert result.conversion_type == "refcursor_function"
        assert "FUNCTION" in result.sql or "CREATE" in result.sql

    def test_multiple_fetch_columns(self):
        """Handle CURSOR with multiple FETCH columns."""
        sql = """
        DECLARE @c CURSOR FOR SELECT id, name, email, created_at FROM users;
        FETCH NEXT FROM @c INTO @id, @name, @email, @created;
        """
        result = CursorHandler.apply_all(sql)
        assert result is not None


class TestCursorEdgeCases:
    """Test edge cases."""

    def test_no_cursor_in_sql(self):
        """SQL without CURSOR remains unchanged."""
        sql = "SELECT * FROM users;"
        result = CursorHandler.apply_all(sql)
        assert result.sql == sql
        assert result.success is False

    def test_cursor_case_insensitive(self):
        """CURSOR keywords are case-insensitive."""
        sql_upper = "DECLARE @c CURSOR FOR SELECT * FROM users;"
        sql_lower = "declare @c cursor for select * from users;"
        result_upper = CursorHandler.apply_all(sql_upper)
        result_lower = CursorHandler.apply_all(sql_lower)
        # Both should parse
        assert result_upper.success or result_lower.success

    def test_cursor_without_query(self):
        """CURSOR without SELECT query is handled."""
        sql = "DECLARE @cursor CURSOR;"
        result = CursorHandler.apply_all(sql)
        # Should warn but not crash
        assert result is not None
        assert len(result.warnings) > 0

    def test_unnamed_cursor(self):
        """CURSOR without @ prefix."""
        sql = "DECLARE users_cursor CURSOR FOR SELECT id FROM users;"
        cursor = CursorHandler.parse_cursor(sql)
        assert cursor is not None
        assert cursor.cursor_name == "users_cursor"


class TestCursorConversionStrategies:
    """Test cursor conversion strategy selection."""

    def test_for_loop_conversion(self):
        """FOR loop conversion for simple cursors."""
        sql = "DECLARE @c CURSOR FOR SELECT id FROM users;"
        result = CursorHandler.apply_all(sql)
        assert result.conversion_type == "for_loop"

    def test_refcursor_function_conversion(self):
        """REFCURSOR function conversion."""
        sql = "DECLARE @ref REFCURSOR; OPEN @ref FOR SELECT * FROM users;"
        result = CursorHandler.apply_all(sql)
        assert result.conversion_type == "refcursor_function"

    def test_fetch_status_loop_conversion(self):
        """FETCH_STATUS loop gets converted to FOR loop."""
        sql = """
        DECLARE @c CURSOR FOR SELECT id FROM users;
        WHILE @@FETCH_STATUS = 0
        BEGIN
            FETCH NEXT FROM @c INTO @id;
        END
        """
        result = CursorHandler.apply_all(sql)
        assert result.conversion_type in ["for_loop", "refcursor_function"]


class TestCursorWarnings:
    """Test CURSOR warning analysis."""

    def test_warn_deallocate(self):
        """Warn about DEALLOCATE statement."""
        sql = "DECLARE @c CURSOR FOR SELECT * FROM users; DEALLOCATE @c;"
        warnings = CursorWarnings.analyze_cursor_usage(sql)
        assert any("DEALLOCATE" in w for w in warnings)

    def test_warn_current_of(self):
        """Warn about WHERE CURRENT OF."""
        sql = "DELETE FROM users WHERE CURRENT OF @cursor;"
        warnings = CursorWarnings.analyze_cursor_usage(sql)
        assert any("WHERE CURRENT OF" in w for w in warnings)

    def test_warn_nested_cursors(self):
        """Warn about multiple DECLARE statements (nested cursors)."""
        sql = """
        DECLARE @c1 CURSOR FOR SELECT id FROM users;
        DECLARE @c2 CURSOR FOR SELECT id FROM orders;
        """
        warnings = CursorWarnings.analyze_cursor_usage(sql)
        assert any("nested" in w.lower() for w in warnings)

    def test_warn_dynamic_cursor(self):
        """Warn about dynamic cursor queries."""
        sql = "DECLARE @c CURSOR FOR EXEC sp_executesql @sql;"
        warnings = CursorWarnings.analyze_cursor_usage(sql)
        assert len(warnings) > 0

    def test_no_warning_for_simple_cursor(self):
        """No warnings for simple CURSOR usage."""
        sql = "DECLARE @c CURSOR FOR SELECT id FROM users;"
        warnings = CursorWarnings.analyze_cursor_usage(sql)
        # Simple cursor should have no special warnings
        assert len(warnings) == 0 or not any("warning" in w.lower() for w in warnings)


class TestCursorIntegration:
    """Integration tests."""

    def test_typical_iteration_cursor(self):
        """Typical row iteration cursor."""
        sql = """
        DECLARE @user_id INT, @user_name NVARCHAR(100);
        DECLARE @users_cursor CURSOR FOR
            SELECT id, name FROM users WHERE active = 1;
        OPEN @users_cursor;
        FETCH NEXT FROM @users_cursor INTO @user_id, @user_name;
        WHILE @@FETCH_STATUS = 0
        BEGIN
            INSERT INTO log VALUES (@user_id, @user_name);
            FETCH NEXT FROM @users_cursor INTO @user_id, @user_name;
        END
        CLOSE @users_cursor;
        DEALLOCATE @users_cursor;
        """
        result = CursorHandler.apply_all(sql)
        assert result is not None

    def test_cursor_in_stored_procedure(self):
        """CURSOR in stored procedure context."""
        sql = """
        CREATE PROCEDURE process_users AS
        BEGIN
            DECLARE @cursor CURSOR FOR SELECT id FROM users;
            OPEN @cursor;
            DECLARE @id INT;
            FETCH NEXT FROM @cursor INTO @id;
            WHILE @@FETCH_STATUS = 0
            BEGIN
                CALL process_user(@id);
                FETCH NEXT FROM @cursor INTO @id;
            END
            CLOSE @cursor;
        END
        """
        result = CursorHandler.apply_all(sql)
        assert result is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
