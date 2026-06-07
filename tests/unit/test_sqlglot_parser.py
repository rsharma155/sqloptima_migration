"""
Module: test_sqlglot_parser.py
Purpose: Unit tests for SQLGlot parser adapter
Author: Migration Platform Team
Created: 2026-05-22
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from domains.parsing.sqlglot_adapter import SqlglotParser


class TestSqlglotParser:
    def setup_method(self):
        self.parser = SqlglotParser()

    def test_parse_simple_select(self):
        result = self.parser.parse("SELECT 1")
        assert result.success is True
        assert result.ast is not None
        assert result.dialect == "tsql"

    def test_parse_create_table(self):
        sql = "CREATE TABLE dbo.users (id INT NOT NULL, name VARCHAR(100))"
        result = self.parser.parse(sql)
        assert result.success is True

    def test_parse_invalid_sql(self):
        result = self.parser.parse("SELEC 1 FROM")
        assert result.success is False
        assert len(result.errors) > 0

    def test_parse_empty_string(self):
        result = self.parser.parse("")
        assert result.success is False

    def test_parse_multiple_statements(self):
        sql = "SELECT 1; SELECT 2"
        results = self.parser.parse_multiple(sql)
        assert len(results) >= 2
        assert all(r.success for r in results)

    def test_transpile_top_to_limit(self):
        sql = "SELECT TOP 10 * FROM users"
        result = self.parser.transpile(sql)
        assert "LIMIT" in result.upper() or "LIMIT" in result

    def test_transpile_isnull_to_coalesce(self):
        sql = "SELECT ISNULL(name, 'N/A') FROM users"
        result = self.parser.transpile(sql)
        assert "COALESCE" in result.upper() or "coalesce" in result

    def test_transpile_getdate_to_current_timestamp(self):
        sql = "SELECT GETDATE()"
        result = self.parser.transpile(sql)
        assert "CURRENT_TIMESTAMP" in result.upper() or "current_timestamp" in result

    def test_dialect_property(self):
        assert self.parser.dialect == "tsql"

    def test_transpile_ast(self):
        result = self.parser.parse("SELECT 1")
        assert result.success and result.ast is not None
        pg_ast = self.parser.transpile_ast(result.ast)
        assert pg_ast is not None
