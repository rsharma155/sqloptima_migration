"""Unit tests for pgparse repair fixers and orchestrator."""

from __future__ import annotations

import pytest

from domains.transpilation.repair.conversion_repair_service import ConversionRepairService
from domains.transpilation.repair.pg_syntax_fixers import (
    fix_apply_to_lateral,
    fix_bracket_identifiers,
    fix_return_query_in_cte,
    fix_table_hints,
)
from domains.validation.postgres_syntax_validator import PostgresSyntaxValidator


class TestPgSyntaxFixers:
    def test_bracket_identifiers(self):
        sql = "SELECT [Order ID] FROM [dbo].[Orders]"
        fixed, count = fix_bracket_identifiers(sql)
        assert count == 3
        assert '"Order ID"' in fixed
        assert '"dbo"' in fixed

    def test_table_hints_removed(self):
        sql = "SELECT * FROM dbo.Orders WITH (NOLOCK, ROWLOCK) WHERE id = 1"
        fixed, count = fix_table_hints(sql)
        assert count == 1
        assert "WITH (NOLOCK" not in fixed

    def test_return_query_removed_inside_cte(self):
        sql = "WITH x AS (\n    RETURN QUERY SELECT 1\n)\nINSERT INTO t SELECT * FROM x"
        fixed, count = fix_return_query_in_cte(sql)
        assert count == 1
        assert "RETURN QUERY" not in fixed.split("WITH x AS")[1].split(")")[0]

    def test_apply_to_lateral(self):
        sql = "SELECT * FROM t CROSS APPLY (SELECT 1) AS s"
        fixed, count = fix_apply_to_lateral(sql)
        assert count == 1
        assert "CROSS JOIN LATERAL" in fixed


class TestConversionRepairService:
    @pytest.fixture
    def repair(self) -> ConversionRepairService:
        return ConversionRepairService(PostgresSyntaxValidator())

    def test_repair_cte_with_return_query(self, repair: ConversionRepairService):
        sql = """CREATE OR REPLACE FUNCTION dbo.fn_test()
RETURNS TABLE(id int)
LANGUAGE plpgsql
AS $function$
BEGIN
    WITH x AS (
        RETURN QUERY SELECT 1 AS id
    )
    RETURN QUERY SELECT id FROM x;
END;
$function$;"""
        result = repair.repair(sql)
        assert "RETURN QUERY SELECT 1" not in result.sql or "WITH x AS (\n        SELECT 1" in result.sql
        assert result.fixes_applied > 0

    def test_repair_valid_sql_unchanged(self, repair: ConversionRepairService):
        sql = "SELECT 1 AS n;"
        result = repair.repair(sql)
        assert result.fixes_applied == 0
        assert result.sql.strip() == sql.strip()
