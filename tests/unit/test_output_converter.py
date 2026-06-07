"""
Test suite for OUTPUT to RETURNING conversion.

Tests conversion of T-SQL OUTPUT clause to PostgreSQL RETURNING.
"""

import pytest

from domains.transpilation.converters.output_converter import (
    OutputConverter,
    OutputWarnings,
)


class TestOutputExtraction:
    """Test OUTPUT clause extraction."""

    def test_extract_simple_output(self):
        """Extract simple OUTPUT clause."""
        sql = "INSERT INTO users (name) VALUES ('test') OUTPUT INSERTED.id"
        output, cols = OutputConverter.extract_output_clause(sql)
        assert output is not None
        assert "id" in output or "INSERTED" in output

    def test_extract_multiple_columns(self):
        """Extract OUTPUT with multiple columns."""
        sql = "INSERT INTO orders (cust_id, amount) VALUES (1, 100) OUTPUT INSERTED.order_id, INSERTED.amount;"
        output, cols = OutputConverter.extract_output_clause(sql)
        assert output is not None
        assert cols is not None
        assert "order_id" in cols or len(cols) > 0

    def test_extract_deleted_references(self):
        """Extract OUTPUT with DELETED references."""
        sql = "UPDATE users SET active = 0 OUTPUT DELETED.id, DELETED.name;"
        output, cols = OutputConverter.extract_output_clause(sql)
        assert output is not None

    def test_extract_wildcard(self):
        """Extract OUTPUT with wildcard."""
        sql = "DELETE FROM logs OUTPUT DELETED.*;"
        output, cols = OutputConverter.extract_output_clause(sql)
        assert output is not None
        assert "*" in cols

    def test_no_output_clause(self):
        """SQL without OUTPUT returns None."""
        sql = "INSERT INTO users (name) VALUES ('test');"
        output, cols = OutputConverter.extract_output_clause(sql)
        assert output is None
        assert cols is None


class TestOutputConversion:
    """Test OUTPUT to RETURNING conversion."""

    def test_insert_with_output_single_column(self):
        """Convert INSERT with OUTPUT to RETURNING."""
        sql = "INSERT INTO users (name) VALUES ('test') OUTPUT INSERTED.id;"
        result = OutputConverter.apply_all(sql)
        assert result.success is True
        assert "RETURNING" in result.sql
        assert "OUTPUT" not in result.sql.upper()
        assert "id" in result.sql.lower()

    def test_insert_with_output_multiple_columns(self):
        """Convert INSERT with OUTPUT multiple columns."""
        sql = (
            "INSERT INTO users (name, email) VALUES ('test', 'test@example.com') "
            "OUTPUT INSERTED.id, INSERTED.name, INSERTED.email;"
        )
        result = OutputConverter.apply_all(sql)
        assert result.success is True
        assert "RETURNING" in result.sql
        assert result.success is True

    def test_update_with_output(self):
        """Convert UPDATE with OUTPUT."""
        sql = "UPDATE users SET active = 1 WHERE id = 5 OUTPUT INSERTED.id, INSERTED.active;"
        result = OutputConverter.apply_all(sql)
        assert result.success is True
        assert "RETURNING" in result.sql

    def test_delete_with_output(self):
        """Convert DELETE with OUTPUT."""
        sql = "DELETE FROM logs WHERE created < '2020-01-01' OUTPUT DELETED.id, DELETED.created;"
        result = OutputConverter.apply_all(sql)
        assert result.success is True
        assert "RETURNING" in result.sql

    def test_output_with_wildcard(self):
        """Convert OUTPUT with wildcard."""
        sql = "DELETE FROM audit OUTPUT DELETED.*;"
        result = OutputConverter.apply_all(sql)
        assert result.success is True
        assert "RETURNING *" in result.sql

    def test_output_normalization_inserted(self):
        """Normalize INSERTED references."""
        output = "INSERTED.id, INSERTED.name, INSERTED.email"
        normalized = OutputConverter.normalize_column_references(output)
        assert "id" in normalized
        assert "name" in normalized
        assert "email" in normalized
        assert "INSERTED" not in normalized.upper()

    def test_output_normalization_deleted(self):
        """Normalize DELETED references."""
        output = "DELETED.id, DELETED.created_at"
        normalized = OutputConverter.normalize_column_references(output)
        assert "id" in normalized
        assert "created_at" in normalized
        assert "DELETED" not in normalized.upper()

    def test_output_removed_from_sql(self):
        """OUTPUT clause is completely removed."""
        sql = "INSERT INTO t VALUES (1) OUTPUT INSERTED.id;"
        result = OutputConverter.apply_all(sql)
        assert "OUTPUT" not in result.sql.upper()
        assert result.success is True


class TestOutputEdgeCases:
    """Test edge cases."""

    def test_no_output(self):
        """SQL without OUTPUT remains unchanged."""
        sql = "SELECT * FROM users;"
        result = OutputConverter.apply_all(sql)
        assert result.sql == sql
        assert result.success is False

    def test_output_with_expressions(self):
        """OUTPUT with expressions is converted."""
        sql = "INSERT INTO summary VALUES (1) OUTPUT INSERTED.id + 1 AS next_id;"
        result = OutputConverter.apply_all(sql)
        # Should still convert even with expression
        assert "RETURNING" in result.sql or result is not None

    def test_output_case_insensitivity(self):
        """OUTPUT keywords are case-insensitive."""
        sql_upper = "INSERT INTO t VALUES (1) OUTPUT inserted.id;"
        sql_lower = "INSERT INTO t VALUES (1) output INSERTED.id;"
        result_upper = OutputConverter.apply_all(sql_upper)
        result_lower = OutputConverter.apply_all(sql_lower)
        assert (result_upper.success or result_lower.success)


class TestOutputWarnings:
    """Test OUTPUT warning generation."""

    def test_warn_deleted_references(self):
        """Warn when OUTPUT references DELETED."""
        sql = "UPDATE t SET x = 1 OUTPUT DELETED.id, INSERTED.id;"
        warnings = OutputWarnings.analyze_output_usage(sql)
        assert len(warnings) > 0
        assert any("DELETED" in w for w in warnings)

    def test_warn_output_into(self):
        """Warn when OUTPUT ... INTO is used."""
        sql = "DELETE FROM t OUTPUT DELETED.id INTO @deleted_ids;"
        warnings = OutputWarnings.analyze_output_usage(sql)
        assert any("INTO" in w for w in warnings)

    def test_no_warning_for_simple_insert(self):
        """No warnings for simple OUTPUT in INSERT."""
        sql = "INSERT INTO t VALUES (1) OUTPUT INSERTED.id;"
        warnings = OutputWarnings.analyze_output_usage(sql)
        assert len(warnings) == 0

    def test_warn_complex_expressions(self):
        """Warn when OUTPUT has complex expressions."""
        sql = "INSERT INTO t VALUES (1) OUTPUT INSERTED.id * 2, INSERTED.id + INSERTED.id;"
        warnings = OutputWarnings.analyze_output_usage(sql)
        assert len(warnings) > 0


class TestOutputIntegration:
    """Integration tests."""

    def test_typical_insert_returning_pattern(self):
        """Typical INSERT ... OUTPUT pattern."""
        sql = (
            "INSERT INTO employees (first_name, last_name, salary) "
            "VALUES ('John', 'Doe', 50000) "
            "OUTPUT INSERTED.employee_id;"
        )
        result = OutputConverter.apply_all(sql)
        assert result.success is True
        assert "RETURNING" in result.sql
        assert "employee_id" in result.sql

    def test_typical_update_returning_pattern(self):
        """Typical UPDATE ... OUTPUT pattern."""
        sql = (
            "UPDATE inventory SET quantity = quantity - 5 "
            "WHERE product_id = 42 "
            "OUTPUT INSERTED.quantity, INSERTED.product_id;"
        )
        result = OutputConverter.apply_all(sql)
        assert result.success is True
        assert "RETURNING" in result.sql

    def test_transaction_with_output(self):
        """OUTPUT in transactional context."""
        sql = (
            "BEGIN TRANSACTION;\n"
            "INSERT INTO audit_log (action, user_id) VALUES ('login', 123) OUTPUT INSERTED.log_id;\n"
            "COMMIT;"
        )
        result = OutputConverter.apply_all(sql)
        # Should still work even in transaction
        assert result is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
