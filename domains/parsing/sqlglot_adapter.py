"""
Module: sqlglot_adapter.py
Purpose: SQLGlot-based T-SQL parser adapter with PIVOT preprocessing
Author: Migration Platform Team
Created: 2026-05-22
Domain: Parsing
Dependencies: sqlglot
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

import re
from typing import Any

import sqlglot
from sqlglot import parse as sqlglot_parse
from sqlglot import parse_one
from sqlglot.errors import ParseError

from domains.parsing.parser_port import ParseResult, SqlParser


class PivotConverter:
    """Converts T-SQL PIVOT clauses to PostgreSQL conditional aggregation.

    T-SQL PIVOT syntax:
        SELECT ...
        FROM (subquery) src
        PIVOT (agg_func(value_col) FOR pivot_col IN ([val1], [val2], ...)) pvt

    PostgreSQL equivalent:
        SELECT ...
            , COALESCE(agg_func(CASE WHEN pivot_col = 'val1' THEN value_col END), 0) AS "val1"
            , ...
        FROM (subquery) src
        GROUP BY <non-pivot, non-value columns>
    """

    PIVOT_RE = re.compile(
        r"""
        PIVOT\s*\(\s*
        (\w+)\s*\(([^)]+)\)\s+        # agg_func(value_col)
        FOR\s+(\w+)\s+IN\s*\(          # FOR pivot_col IN (
        ([^)]+)\)\s*\)                 # [val1], [val2], ...
        \s*(?:AS\s+)?(\w+)?            # optional alias
        """,
        re.IGNORECASE | re.VERBOSE | re.DOTALL,
    )

    UNPIVOT_RE = re.compile(
        r"""
        UNPIVOT\s*\(\s*
        (\w+)\s+FOR\s+(\w+)\s+IN\s*\(  # value_col FOR pivot_col IN (
        ([^)]+)\)\s*\)                 # [col1], [col2], ...
        \s*(?:AS\s+)?(\w+)?
        """,
        re.IGNORECASE | re.VERBOSE | re.DOTALL,
    )

    @classmethod
    def preprocess(cls, sql: str) -> str:
        """Preprocess SQL to replace PIVOT/UNPIVOT with PostgreSQL equivalents."""
        sql = cls._convert_pivot(sql)
        sql = cls._convert_unpivot(sql)
        return sql

    @classmethod
    def _convert_pivot(cls, sql: str) -> str:
        match = cls.PIVOT_RE.search(sql)
        if not match:
            return sql

        agg_func = match.group(1)
        value_col = match.group(2).strip()
        pivot_col = match.group(3)
        pivot_values_raw = match.group(4)
        pivot_alias = match.group(5) or "pvt"

        pivot_values = re.findall(r'\[([^\]]+)\]', pivot_values_raw)
        if not pivot_values:
            pivot_values = [v.strip().strip('"').strip("'").strip("[]") for v in pivot_values_raw.split(",")]

        before_pivot = sql[:match.start()].rstrip()
        after_pivot = sql[match.end():].lstrip()

        subquery_match = re.search(r'FROM\s*\(\s*([\s\S]*?)\s*\)\s*\w+$', before_pivot, re.IGNORECASE)
        if not subquery_match:
            return sql

        subquery_body = subquery_match.group(1).strip()
        after_close = before_pivot[subquery_match.end():].strip()
        subquery_alias = after_close.split()[0] if after_close else "src"

        select_cols = cls._extract_select_columns(subquery_body)
        group_cols = cls._select_non_pivot_columns(select_cols, pivot_col, value_col)

        agg_exprs = []
        for val in pivot_values:
            safe_val = val.replace("'", "''")
            case_when = (
                f"{agg_func}(CASE WHEN {subquery_alias}.{pivot_col} = '{safe_val}' "
                f"THEN {subquery_alias}.{value_col} END)"
            )
            agg_exprs.append(f"COALESCE({case_when}, 0) AS \"{val}\"")

        if group_cols:
            group_by = "GROUP BY " + ", ".join(f"{subquery_alias}.{c}" for c in group_cols)
        else:
            group_by = ""

        select_list = []
        if group_cols:
            select_list = [f"{subquery_alias}.{c}" for c in group_cols]
        else:
            select_list = [f"{subquery_alias}.*"]
        select_list.extend(agg_exprs)

        pg_sql = f"{'SELECT ' + ', '.join(select_list)} FROM ({subquery_body}) {subquery_alias}"
        if group_by:
            pg_sql += "\n" + group_by

        if after_pivot:
            pg_sql += " " + after_pivot

        return pg_sql

    @classmethod
    def _convert_unpivot(cls, sql: str) -> str:
        match = cls.UNPIVOT_RE.search(sql)
        if not match:
            return sql

        value_col = match.group(1)
        pivot_col = match.group(2)
        unpivot_cols_raw = match.group(3)
        unpivot_alias = match.group(4) or "unpvt"

        unpivot_cols = re.findall(r'\[([^\]]+)\]', unpivot_cols_raw)
        if not unpivot_cols:
            unpivot_cols = [c.strip().strip('"').strip("'") for c in unpivot_cols_raw.split(",")]

        before_unpivot = sql[:match.start()].rstrip()
        after_unpivot = sql[match.end():].lstrip()

        cross_joins = []
        for col in unpivot_cols:
            cross_joins.append(
                f"SELECT *, '{col}' AS {pivot_col}, {col} AS {value_col}"
            )
        union_all = "\n    UNION ALL\n    ".join(cross_joins)

        pg_sql = f"SELECT * FROM (\n    {union_all}\n) {unpivot_alias}"

        if after_unpivot:
            pg_sql += " " + after_unpivot

        return pg_sql

    @staticmethod
    def _extract_select_columns(subquery_body: str) -> list[str]:
        stripped = subquery_body.strip()
        if stripped.upper().startswith("SELECT"):
            select_part = stripped[6:].strip()
        else:
            return []

        from_idx = _find_top_level_keyword(select_part.upper(), "FROM")
        if from_idx >= 0:
            select_part = select_part[:from_idx].strip()

        cols = []
        for item in _split_select_list(select_part):
            item = item.strip()
            if not item:
                continue
            as_idx = _find_top_level_keyword(item.upper(), "AS")
            if as_idx >= 0:
                alias_part = item[as_idx + 2:].strip()
                alias = alias_part.split()[0].strip('"[]')
                cols.append(alias)
            else:
                parts = item.split()
                if len(parts) > 1:
                    alias = parts[-1].strip('"[]')
                    if alias.upper() not in ("FROM",):
                        cols.append(alias)
                    else:
                        cols.append(parts[0].strip('"[]'))
                else:
                    name = parts[0].strip('"[]')
                    dot_idx = name.rfind(".")
                    if dot_idx >= 0:
                        name = name[dot_idx + 1:]
                    cols.append(name)

        return cols

    @staticmethod
    def _select_non_pivot_columns(columns: list[str], pivot_col: str, value_col: str) -> list[str]:
        pivot_col_upper = pivot_col.upper()
        value_col_upper = value_col.upper()
        return [c for c in columns if c.upper() not in (pivot_col_upper, value_col_upper)]


def _find_top_level_keyword(text: str, keyword: str) -> int:
    depth = 0
    in_string = False
    string_char = None
    for i, ch in enumerate(text):
        if in_string:
            if ch == string_char:
                in_string = False
            continue
        if ch in ("'", '"'):
            in_string = True
            string_char = ch
            continue
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif depth == 0 and text[i:i+len(keyword)].upper() == keyword:
            if (i == 0 or not text[i-1].isalnum()) and (i+len(keyword) >= len(text) or not text[i+len(keyword)].isalnum()):
                return i
    return -1


def _split_select_list(select_part: str) -> list[str]:
    items = []
    depth = 0
    current = ""
    for ch in select_part:
        if ch == '(':
            depth += 1
            current += ch
        elif ch == ')':
            depth -= 1
            current += ch
        elif ch == ',' and depth == 0:
            items.append(current)
            current = ""
        else:
            current += ch
    if current.strip():
        items.append(current)
    return items


class SqlglotParser(SqlParser):
    """Parses T-SQL using SQLGlot and generates PostgreSQL.

    Primary parser for the platform. Falls back gracefully on parse errors.
    Includes PIVOT/UNPIVOT preprocessing for constructs sqlglot silently drops.
    """

    READ_DIALECT = "tsql"
    WRITE_DIALECT = "postgres"

    def __init__(self, error_level: int = 0):
        self._error_level = error_level

    def parse(self, sql: str) -> ParseResult:
        """Parse a single T-SQL statement into AST."""
        try:
            preprocessed = PivotConverter.preprocess(sql)
            tree = parse_one(preprocessed, read=self.READ_DIALECT, error_level=self._error_level)
            return ParseResult(success=True, ast=tree, dialect=self.READ_DIALECT)
        except ParseError as e:
            return ParseResult(success=False, errors=[str(e)], dialect=self.READ_DIALECT)
        except Exception as e:
            return ParseResult(success=False, errors=[f"Unexpected error: {e}"], dialect=self.READ_DIALECT)

    def parse_multiple(self, sql: str) -> list[ParseResult]:
        """Parse multiple T-SQL statements."""
        try:
            preprocessed = PivotConverter.preprocess(sql)
            trees = sqlglot_parse(preprocessed, read=self.READ_DIALECT, error_level=self._error_level)
            return [
                ParseResult(success=True, ast=t, dialect=self.READ_DIALECT) for t in trees
            ]
        except ParseError as e:
            return [ParseResult(success=False, errors=[str(e)], dialect=self.READ_DIALECT)]
        except Exception as e:
            return [ParseResult(success=False, errors=[f"Unexpected error: {e}"], dialect=self.READ_DIALECT)]

    def transpile(self, sql: str) -> str:
        """Transpile T-SQL to PostgreSQL SQL directly."""
        try:
            preprocessed = PivotConverter.preprocess(sql)
            result = sqlglot.transpile(preprocessed, read=self.READ_DIALECT, write=self.WRITE_DIALECT)
            return "\n".join(result)
        except Exception:
            return ""

    def transpile_ast(self, ast: Any) -> Any | None:
        """Transpile an AST node to PostgreSQL dialect."""
        try:
            if hasattr(ast, "sql"):
                pg_sql = ast.sql(dialect=self.WRITE_DIALECT)
                return parse_one(pg_sql, read=self.WRITE_DIALECT)
        except Exception:
            return None
        return None

    @property
    def dialect(self) -> str:
        return self.READ_DIALECT
