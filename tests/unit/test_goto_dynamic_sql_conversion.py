"""Regression tests for GOTO and sp_executesql conversion in procedures."""

from __future__ import annotations

import re

from application.conversion_factory import build_conversion_service
from application.conversion_service import ConversionRequest


def _convert(sql: str, name: str = "test_proc") -> str:
    svc = build_conversion_service("dbo", "public")
    result = svc.convert(
        ConversionRequest(sql=sql, object_type="procedure", schema="dbo", name=name),
    )
    assert result.success, result.errors
    assert result.postgres_syntax_valid, result.errors
    assert result.converted_sql
    return result.converted_sql


def _no_goto_remnant(sql: str) -> None:
    assert not re.search(r"\bGOTO\b", sql, re.IGNORECASE)


def _no_sp_executesql_remnant(sql: str) -> None:
    assert not re.search(r"\bsp_executesql\b", sql, re.IGNORECASE)


def test_goto_and_label_convert_without_remnants() -> None:
    sql = """CREATE PROCEDURE dbo.usp_goto @x INT AS BEGIN
IF @x = 1 GOTO done;
SELECT 1;
done:
SELECT 2;
END;"""
    out = _convert(sql, "usp_goto")
    _no_goto_remnant(out)
    _no_sp_executesql_remnant(out)


def test_sp_executesql_multiline_with_goto() -> None:
    sql = """CREATE PROCEDURE dbo.IndexOptimize AS BEGIN
DECLARE @sql NVARCHAR(MAX);
SET @sql = N'SELECT 1';
EXEC sp_executesql @sql,
    N'@Database NVARCHAR(128)',
    @Database = N'master';
GOTO ExitProcedure;
ExitProcedure:
RETURN;
END;"""
    out = _convert(sql, "IndexOptimize")
    _no_sp_executesql_remnant(out)
    _no_goto_remnant(out)
    assert "EXECUTE v_sql" in out


def test_execute_sp_executesql_variant() -> None:
    sql = """CREATE PROCEDURE dbo.p AS BEGIN
DECLARE @sql NVARCHAR(MAX)=N'SELECT 1';
EXECUTE sp_executesql @sql;
END;"""
    out = _convert(sql, "p")
    _no_sp_executesql_remnant(out)
    assert "EXECUTE v_sql" in out
