"""Tests for resilient transpiler (Phase C)."""

from __future__ import annotations

from domains.parsing.resilient_transpiler import ResilientTranspiler


class TestResilientTranspiler:
    def test_transpiles_simple_select(self):
        rt = ResilientTranspiler()
        result = rt.transpile_with_metadata("SELECT GETDATE() AS today")
        assert result.success
        assert "NOW()" in result.sql.upper() or "CURRENT" in result.sql.upper()

    def test_unblockers_applied_on_bracket_sql(self):
        rt = ResilientTranspiler()
        sql = "SELECT [col] FROM [dbo].[t] WITH (NOLOCK)"
        result = rt.transpile_with_metadata(sql)
        assert result.unblockers_applied or result.success

    def test_returns_parse_errors_for_invalid_sql(self):
        rt = ResilientTranspiler()
        result = rt.transpile_with_metadata("SELECT FROM WHERE")
        assert not result.success
        assert result.sql == ""
