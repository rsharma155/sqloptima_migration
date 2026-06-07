"""Tests for T-SQL parse unblockers (Phase C)."""

from __future__ import annotations

from domains.parsing.tsql_parse_unblocker import TsqlParseUnblocker


class TestTsqlParseUnblocker:
    def test_strip_go_and_brackets(self):
        sql = """
        CREATE PROCEDURE [dbo].[usp_test]
        AS
        BEGIN
            SELECT [OrderID] FROM [dbo].[Orders]
        END
        GO
        """
        result = TsqlParseUnblocker.apply(sql)
        assert "GO" not in result.sql.split("END")[-1]
        assert "[dbo]" not in result.sql
        assert "usp_test" in result.sql
        assert result.steps_applied

    def test_aggressive_strips_procedure_options(self):
        sql = "CREATE PROCEDURE dbo.p WITH ENCRYPTION AS BEGIN SELECT 1 END"
        result = TsqlParseUnblocker.apply(sql, aggressive=True)
        assert "WITH ENCRYPTION" not in result.sql
        assert "strip_procedure_options" in result.steps_applied

    def test_comment_goto(self):
        sql = "BEGIN\n    GOTO cleanup;\n    SELECT 1;\n    cleanup:\n    RETURN;\nEND"
        result = TsqlParseUnblocker.apply(sql, aggressive=True)
        assert "GOTO cleanup" not in result.sql
