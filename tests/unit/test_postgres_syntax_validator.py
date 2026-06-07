"""Unit tests for PostgreSQL syntax validation of converted output."""

from __future__ import annotations

import pytest

from domains.validation.postgres_syntax_validator import PostgresSyntaxValidator


@pytest.fixture
def validator() -> PostgresSyntaxValidator:
    return PostgresSyntaxValidator()


class TestPostgresSyntaxValidator:
    def test_valid_simple_select(self, validator: PostgresSyntaxValidator) -> None:
        result = validator.validate("SELECT id, name FROM users LIMIT 10;")
        assert result.valid is True
        assert result.errors == []

    def test_detects_nolock_remnant(self, validator: PostgresSyntaxValidator) -> None:
        result = validator.validate("SELECT * FROM users WITH (NOLOCK);")
        assert result.valid is False
        assert any("NOLOCK" in issue.message for issue in result.errors)

    def test_detects_sp_executesql_remnant(self, validator: PostgresSyntaxValidator) -> None:
        result = validator.validate("EXEC sp_executesql v_sql;")
        assert result.valid is False
        assert any("sp_executesql" in issue.message for issue in result.errors)

    def test_detects_goto_remnant(self, validator: PostgresSyntaxValidator) -> None:
        result = validator.validate("GOTO error_handler;")
        assert result.valid is False
        assert any("GOTO" in issue.message for issue in result.errors)

    def test_empty_sql_is_invalid(self, validator: PostgresSyntaxValidator) -> None:
        result = validator.validate("   ")
        assert result.valid is False
        assert result.errors[0].message == "Converted SQL is empty"

    def test_valid_plpgsql_function(self, validator: PostgresSyntaxValidator) -> None:
        sql = """
CREATE OR REPLACE FUNCTION dbo.usp_test()
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM 1;
END;
$$;
"""
        result = validator.validate(sql)
        assert result.valid is True

    def test_invalid_plpgsql_body_with_goto(self, validator: PostgresSyntaxValidator) -> None:
        sql = """
CREATE OR REPLACE FUNCTION dbo.usp_test()
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    IF 1 = 1 THEN GOTO error_handler; END IF;
END;
$$;
"""
        result = validator.validate(sql)
        assert result.valid is False
        assert any("GOTO" in issue.message for issue in result.errors)

    def test_skips_insert_execute_dynamic_sql(self, validator: PostgresSyntaxValidator) -> None:
        sql = """
CREATE OR REPLACE FUNCTION dbo.usp_stats()
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    CREATE TEMP TABLE tmp_results (value INT);
    INSERT INTO tmp_results EXECUTE v_sql;
END;
$$;
"""
        result = validator.validate(sql)
        assert result.valid is True
        assert result.errors == []
