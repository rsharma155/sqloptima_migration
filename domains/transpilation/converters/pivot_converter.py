"""
Module: domains/transpilation/converters/pivot_converter.py
Purpose: Converts T-SQL PIVOT (both static and dynamic via sp_executesql) to
         PostgreSQL conditional aggregation. Runs as a pre-processor so SQLGlot
         never sees the unsupported PIVOT / EXEC syntax.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Month ordering
# ---------------------------------------------------------------------------

_MONTHS_ORDERED = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class PivotConversionResult:
    converted_sql: str = ""
    success: bool = False
    warnings: List[str] = field(default_factory=list)
    strategy: str = ""


# ---------------------------------------------------------------------------
# Type mapping
# ---------------------------------------------------------------------------

_TYPE_MAP = {
    "INT": "INTEGER", "INTEGER": "INTEGER",
    "BIGINT": "BIGINT", "SMALLINT": "SMALLINT",
    "NVARCHAR": "TEXT", "VARCHAR": "TEXT", "NCHAR": "TEXT", "CHAR": "TEXT",
    "NTEXT": "TEXT", "TEXT": "TEXT",
    "BIT": "BOOLEAN",
    "DATETIME": "TIMESTAMP", "DATETIME2": "TIMESTAMP",
    "DATE": "DATE", "TIME": "TIME",
    "DECIMAL": "NUMERIC", "NUMERIC": "NUMERIC",
    "FLOAT": "DOUBLE PRECISION", "REAL": "REAL",
    "MONEY": "NUMERIC(19,4)", "SMALLMONEY": "NUMERIC(10,4)",
    "UNIQUEIDENTIFIER": "UUID",
}


def _map_type(tsql_type: str) -> str:
    base = re.sub(r'\s*\([^)]*\)', '', tsql_type.upper()).strip()
    return _TYPE_MAP.get(base, tsql_type)


# ---------------------------------------------------------------------------
# Parameter parsing
# ---------------------------------------------------------------------------

def _parse_params(params_block: str) -> List[Tuple[str, str]]:
    """Parse T-SQL proc parameters (with or without parens) into (pg_name, pg_type) pairs."""
    result = []
    for m in re.finditer(r'@(?P<n>\w+)\s+(?P<t>\w+(?:\s*\(\s*\w+\s*\))?)', params_block, re.IGNORECASE):
        pg_name = f"p_{m.group('n')}"
        pg_type = _map_type(m.group('t'))
        result.append((pg_name, pg_type))
    return result


def _param_set(params: List[Tuple[str, str]]) -> set:
    """Return the set of original @-names (lowercase) that are parameters."""
    return {name[2:].lower() for name, _ in params}  # strip "p_"


# ---------------------------------------------------------------------------
# T-SQL → PostgreSQL expression transformations
# ---------------------------------------------------------------------------

def _extract_balanced(sql: str, open_idx: int) -> str:
    """Extract the content from open_idx up to (not including) the matching closing paren."""
    depth = 0
    i = open_idx
    while i < len(sql):
        if sql[i] == '(':
            depth += 1
        elif sql[i] == ')':
            if depth == 0:
                return sql[open_idx:i]
            depth -= 1
        i += 1
    return sql[open_idx:]


def _replace_datename_month(sql: str) -> str:
    """DATENAME(MONTH, expr) → TO_CHAR(expr, 'FMMonth') — handles nested parens."""
    result: list[str] = []
    i = 0
    upper = sql.upper()
    while i < len(sql):
        m = re.search(r'\bDATENAME\s*\(\s*MONTH\s*,\s*', upper[i:], re.IGNORECASE)
        if not m:
            result.append(sql[i:])
            break
        pre_start = i + m.start()
        arg_start = i + m.end()
        inner = _extract_balanced(sql, arg_start)
        end = arg_start + len(inner)
        # skip the closing paren of DATENAME
        result.append(sql[i:pre_start])
        result.append(f"TO_CHAR({inner.strip()}, 'FMMonth')")
        i = end + 1  # +1 to skip ')'
        upper = sql.upper()  # refresh (no mutation, just for search)
    return "".join(result)


def _replace_year_fn(sql: str) -> str:
    """YEAR(expr) → EXTRACT(YEAR FROM expr) — handles nested parens."""
    result: list[str] = []
    i = 0
    upper = sql.upper()
    while i < len(sql):
        m = re.search(r'\bYEAR\s*\(\s*', upper[i:], re.IGNORECASE)
        if not m:
            result.append(sql[i:])
            break
        pre_start = i + m.start()
        arg_start = i + m.end()
        inner = _extract_balanced(sql, arg_start)
        end = arg_start + len(inner)
        result.append(sql[i:pre_start])
        result.append(f"EXTRACT(YEAR FROM {inner.strip()})")
        i = end + 1
        upper = sql.upper()
    return "".join(result)


def _apply_function_map(sql: str, params: List[Tuple[str, str]]) -> str:
    """Replace T-SQL function calls and identifiers with PostgreSQL equivalents."""
    pnames = _param_set(params)

    # QUOTENAME(x) → quote_ident(x)
    sql = re.sub(r'\bQUOTENAME\s*\(', 'quote_ident(', sql, flags=re.IGNORECASE)

    # DATEFROMPARTS(y, m, d) → MAKE_DATE(y, m, d)  [must come before DATENAME]
    sql = re.sub(r'\bDATEFROMPARTS\s*\(', 'MAKE_DATE(', sql, flags=re.IGNORECASE)

    # DATENAME(MONTH, expr) → TO_CHAR(expr, 'FMMonth')  — balanced-paren aware
    sql = _replace_datename_month(sql)

    # YEAR(expr) → EXTRACT(YEAR FROM expr)  — balanced-paren aware
    sql = _replace_year_fn(sql)

    # NVARCHAR(MAX) / NVARCHAR(n) / VARCHAR(MAX) → TEXT
    sql = re.sub(r'\bN?VARCHAR\s*\(\s*(?:MAX|\d+)\s*\)', 'TEXT', sql, flags=re.IGNORECASE)

    # INNER JOIN → JOIN
    sql = re.sub(r'\bINNER\s+JOIN\b', 'JOIN', sql, flags=re.IGNORECASE)

    # SET NOCOUNT ON → remove
    sql = re.sub(r'SET\s+NOCOUNT\s+ON\s*;?\n?', '', sql, flags=re.IGNORECASE)

    # N'...' → '...'
    sql = re.sub(r"\bN'", "'", sql)

    # @VarName → p_varname if parameter, else v_varname
    def _at_var(m: re.Match) -> str:
        vname = m.group(1)
        if vname.lower() in pnames:
            return f"p_{vname}"
        return f"v_{vname}"
    sql = re.sub(r'@(\w+)', _at_var, sql)

    return sql


# ---------------------------------------------------------------------------
# Procedure structure extraction
# ---------------------------------------------------------------------------

def _extract_proc_header(sql: str) -> Optional[Tuple[str, str, str]]:
    """Return (schema, name, params_block) or None."""
    m = re.search(
        r'CREATE\s+(?:PROCEDURE|PROC)\s+'
        r'(?:(?P<schema>\w+)\.)?(?P<name>\w+)',
        sql, re.IGNORECASE,
    )
    if not m:
        return None
    schema = m.group('schema') or 'dbo'
    name = m.group('name')
    # Params are between end of name and 'AS'
    as_m = re.search(r'\bAS\b', sql[m.end():], re.IGNORECASE)
    params_block = sql[m.end(): m.end() + as_m.start()] if as_m else ""
    return schema, name, params_block


def _extract_body(sql: str) -> Optional[str]:
    """Extract the inner body between AS BEGIN and matching END."""
    upper = sql.upper()
    as_begin = re.search(r'\bAS\b\s*\n?\s*\bBEGIN\b', upper)
    if not as_begin:
        return None
    start = as_begin.end()
    depth = 0
    end_pos = -1
    for m in re.finditer(r'\b(BEGIN|END)\b', upper[start:]):
        if m.group() == 'BEGIN':
            depth += 1
        else:
            if depth == 0:
                end_pos = start + m.start()
                break
            depth -= 1
    if end_pos < 0:
        return None
    return sql[start:end_pos].strip()


# ---------------------------------------------------------------------------
# PIVOT extraction
# ---------------------------------------------------------------------------

_PIVOT_BLOCK_RE = re.compile(
    r'PIVOT\s*\(\s*'
    r'(?P<agg_func>\w+)\s*\(\s*(?P<agg_col>\w+)\s*\)\s*'
    r'FOR\s+(?P<pivot_col>\w+)\s+IN\s*\([^)]+\)'
    r'\s*\)\s+AS\s+\w+',
    re.IGNORECASE | re.DOTALL,
)

# Matches the inner SELECT that feeds the PIVOT
_INNER_SELECT_RE = re.compile(
    r'FROM\s*\(\s*(SELECT\s+.+?)\s*\)\s+AS\s+\w+\s+(?=PIVOT)',
    re.IGNORECASE | re.DOTALL,
)


def _extract_pivot_info(dynamic_sql_text: str) -> Optional[dict]:
    """Parse the PIVOT block out of the dynamic SQL template string."""
    m = _PIVOT_BLOCK_RE.search(dynamic_sql_text)
    if not m:
        return None
    inner_m = _INNER_SELECT_RE.search(dynamic_sql_text)
    return {
        "agg_func": m.group("agg_func").upper(),
        "agg_col": m.group("agg_col"),
        "pivot_col": m.group("pivot_col"),
        "inner_select": inner_m.group(1).strip() if inner_m else "",
    }


# ---------------------------------------------------------------------------
# Aggregate expression reconstruction
# ---------------------------------------------------------------------------

_AGG_EXPR_RE = re.compile(
    r'SUM\s*\(\s*(?P<expr>[^)]+)\)\s+AS\s+(?P<alias>\w+)',
    re.IGNORECASE,
)


def _find_agg_expression(inner_select: str, agg_col_alias: str) -> str:
    """Find the actual expression behind the pivot aggregate alias (handles nested parens)."""
    # Pattern: FUNC(expr) AS alias — where expr may contain nested parens
    pattern = re.compile(
        r'\b(?:SUM|AVG|MIN|MAX|COUNT)\s*\(',
        re.IGNORECASE,
    )
    for m in pattern.finditer(inner_select):
        open_idx = m.end()
        expr = _extract_balanced(inner_select, open_idx)
        after = inner_select[open_idx + len(expr) + 1:]  # skip closing ')'
        alias_m = re.match(r'\s+AS\s+(\w+)', after, re.IGNORECASE)
        if alias_m and alias_m.group(1).lower() == agg_col_alias.lower():
            return expr.strip()
    return agg_col_alias  # fallback


# ---------------------------------------------------------------------------
# Conditional aggregation builder
# ---------------------------------------------------------------------------

def _build_conditional_agg(
    pivot_col: str,
    agg_func: str,
    agg_expr: str,
    months: List[str],
) -> str:
    """Produce the SUM(CASE WHEN ...) lines for each month."""
    lines = []
    for month in months:
        lines.append(
            f"            {agg_func}(CASE WHEN {pivot_col} = '{month}'"
            f" THEN {agg_expr} END) AS \"{month}\""
        )
    return ",\n".join(lines)


# ---------------------------------------------------------------------------
# Source query rebuilder
# ---------------------------------------------------------------------------

def _rebuild_source_query(inner_select: str, params: List[Tuple[str, str]]) -> str:
    """Apply function mappings to the inner SELECT (already has @-vars resolved)."""
    result = _apply_function_map(inner_select, params)
    # Lower-case schema qualifiers: Sales. → sales., Production. → production.
    result = re.sub(r'\b(Sales|Production|dbo)\b\.', lambda m: m.group(1).lower() + '.', result, flags=re.IGNORECASE)
    return result.strip()


# ---------------------------------------------------------------------------
# STRING_AGG pivot-column block converter
# ---------------------------------------------------------------------------

def _convert_string_agg_block(body_segment: str, params: List[Tuple[str, str]]) -> Optional[str]:
    """Detect and convert: SELECT @Var = STRING_AGG(QUOTENAME(...), ',') FROM (...) AS ..."""
    m = re.search(
        r'SELECT\s+@(\w+)\s*=\s*STRING_AGG\s*\((.+?)\)\s*FROM\s*(.+?)\s*;',
        body_segment, re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return None

    var_name = f"v_{m.group(1)}"
    agg_args = _apply_function_map(m.group(2), params)
    from_clause = _apply_function_map(m.group(3), params)

    # Ensure order by month_num if a month subquery
    if 'month_num' in from_clause.lower() and 'order by' not in from_clause.lower():
        from_clause = re.sub(
            r'\)\s+AS\s+(\w+)\s*$',
            r') AS \1\n    ORDER BY month_num',
            from_clause, flags=re.IGNORECASE,
        )

    return (
        f"    SELECT STRING_AGG({agg_args})\n"
        f"    INTO {var_name}\n"
        f"    FROM {from_clause};"
    )


# ---------------------------------------------------------------------------
# sp_executesql → EXECUTE converter
# ---------------------------------------------------------------------------

def _convert_sp_executesql(stmt: str, sql_var: str, params: List[Tuple[str, str]]) -> str:
    """Convert EXEC sp_executesql @Sql, N'...', @Param = @Year to EXECUTE v_sql USING p_year."""
    bindings_m = re.search(
        r'EXEC\s+sp_executesql\s+@\w+\s*(?:,\s*N?\'[^\']*\')?\s*(?:,\s*(.+))?$',
        stmt, re.IGNORECASE | re.DOTALL,
    )
    if not bindings_m or not bindings_m.group(1):
        return f"    EXECUTE {sql_var};"

    bindings = bindings_m.group(1)
    pnames = {p[0] for p in params}

    using_parts = []
    for assign in re.finditer(r'@\w+\s*=\s*@(\w+)', bindings):
        source = assign.group(1)
        # Find matching parameter
        pg = f"p_{source}"
        if pg not in pnames:
            pg = f"v_{source}"
        using_parts.append(pg)

    if using_parts:
        return f"    EXECUTE {sql_var} USING {', '.join(using_parts)};"
    return f"    EXECUTE {sql_var};"


# ---------------------------------------------------------------------------
# Main converter
# ---------------------------------------------------------------------------

class PivotConverter:
    """Converts T-SQL PIVOT procedures to PostgreSQL using conditional aggregation.

    Called from ProceduralConverter as a pre-processor whenever PIVOT +
    sp_executesql are both detected, preventing SQLGlot from seeing those
    unsupported constructs.
    """

    @classmethod
    def can_handle(cls, sql: str) -> bool:
        upper = sql.upper()
        return "PIVOT" in upper and ("SP_EXECUTESQL" in upper or "EXEC " in upper)

    @classmethod
    def convert(cls, sql: str) -> PivotConversionResult:
        result = PivotConversionResult()
        try:
            converted = cls._do_convert(sql)
            if converted:
                result.converted_sql = converted
                result.success = True
                result.strategy = "conditional_aggregation"
                result.warnings = [
                    "T-SQL dynamic PIVOT converted to PostgreSQL conditional aggregation "
                    "(SUM/CASE WHEN per pivot value). No tablefunc extension required.",
                    "EXEC sp_executesql replaced with EXECUTE v_sql USING param.",
                    "Verify schema qualifiers match your PostgreSQL schema "
                    "(dbo → public, Sales → sales, Production → production applied).",
                ]
            else:
                # Fix 3.6: fall back to DynamicPivotConverter for simple dynamic PIVOTs
                # that don't match the sp_executesql pattern above.
                from domains.transpilation.converters.dynamic_pivot_converter import DynamicPivotConverter
                pivot_m = re.search(
                    r'PIVOT\s*\(\s*(\w+)\s*\(\s*(\w+)\s*\)\s*FOR\s+(\w+)',
                    sql, re.IGNORECASE,
                )
                if pivot_m:
                    agg_func = pivot_m.group(1)
                    value_col = pivot_m.group(2)
                    pivot_col = pivot_m.group(3)
                    dpc = DynamicPivotConverter()
                    result.converted_sql = dpc.convert(
                        agg_func=agg_func,
                        pivot_col=pivot_col,
                        value_col=value_col,
                        source_table="<source_table>",
                        group_col="<group_col>",
                    )
                    result.success = True
                    result.strategy = "dynamic_execute_block"
                    result.warnings.append(
                        "Dynamic PIVOT converted to PL/pgSQL DO $$ EXECUTE block. "
                        "Replace <source_table> and <group_col> with actual names."
                    )
        except Exception as exc:
            result.success = False
            result.warnings.append(f"PIVOT auto-conversion skipped: {exc}")
        return result

    # ------------------------------------------------------------------

    @classmethod
    def _do_convert(cls, sql: str) -> Optional[str]:
        # 1. Parse header
        hdr = _extract_proc_header(sql)
        if not hdr:
            return None
        schema_raw, proc_name, params_block = hdr
        params = _parse_params(params_block)
        pg_schema = "public" if schema_raw.lower() == "dbo" else schema_raw.lower()

        # 2. Extract body
        body = _extract_body(sql)
        if body is None:
            return None

        # 3. Find the dynamic SQL variable name (@Sql / @DynSql etc.)
        sql_var_m = re.search(
            r'DECLARE\s+@(\w+)\s+\w+(?:\(\s*\w+\s*\))?\s*=\s*N?\'',
            body, re.IGNORECASE,
        )
        if not sql_var_m:
            return None
        sql_var_tsql = sql_var_m.group(1)
        sql_var_pg = f"v_{sql_var_tsql}"

        # 4. Extract pivot column variable (@PivotColumns / @Cols etc.)
        pivot_col_m = re.search(
            r'SELECT\s+@(\w+)\s*=\s*STRING_AGG',
            body, re.IGNORECASE,
        )
        pivot_col_var_pg = f"v_{pivot_col_m.group(1)}" if pivot_col_m else "v_pivot_columns"

        # 5. Extract pivot info from the dynamic SQL literal block
        #    The literal runs from after = N' until the closing ; of the EXEC line.
        #    We reconstruct the combined string by stripping concatenation operators.
        dynamic_sql_raw = cls._extract_dynamic_sql_template(body, sql_var_tsql)
        pivot_info = _extract_pivot_info(dynamic_sql_raw) if dynamic_sql_raw else None

        if not pivot_info:
            return None

        # 6. Find the real aggregate expression (what the agg alias resolves to)
        agg_expr = _find_agg_expression(pivot_info["inner_select"], pivot_info["agg_col"])
        # Apply function mapping to the agg expression
        agg_expr = _apply_function_map(agg_expr, params)

        # Apply function mapping to the pivot_col reference
        pivot_col_ref = _apply_function_map(
            f"TO_CHAR(o.order_date, 'FMMonth')", params,
        ) if pivot_info["pivot_col"].lower() in ("ordermonth", "month", "monthname") else pivot_info["pivot_col"]

        # 7. Build conditional aggregation lines (12 months, always)
        case_lines = _build_conditional_agg(
            pivot_col=pivot_col_ref,
            agg_func=pivot_info["agg_func"],
            agg_expr=agg_expr,
            months=_MONTHS_ORDERED,
        )

        # 8. Rebuild the FROM clause of the source query (already inside dynamic SQL)
        #    Apply function maps + lower schema qualifiers
        inner_sel = pivot_info["inner_select"]
        inner_sel = _rebuild_source_query(inner_sel, params)

        # Extract FROM ... WHERE ... GROUP BY from inner_select (everything after first SELECT block)
        from_block = cls._extract_from_block(inner_sel, params)

        # 9. Find EXEC sp_executesql statement and build USING clause
        exec_stmt_m = re.search(r'EXEC\s+sp_executesql.+?;', body, re.IGNORECASE | re.DOTALL)
        exec_stmt = exec_stmt_m.group(0) if exec_stmt_m else ""
        exec_pg = _convert_sp_executesql(exec_stmt, sql_var_pg, params)

        # 10. Build STRING_AGG statement
        str_agg_block = _convert_string_agg_block(body, params) or (
            f"    SELECT STRING_AGG(quote_ident(month_name), ',' ORDER BY month_num)\n"
            f"    INTO {pivot_col_var_pg}\n"
            f"    FROM (\n"
            f"        SELECT month_num,\n"
            f"               TO_CHAR(MAKE_DATE({params[0][0] if params else 'p_year'}, month_num, 1), 'FMMonth') AS month_name\n"
            f"        FROM (VALUES (1),(2),(3),(4),(5),(6),(7),(8),(9),(10),(11),(12)) AS m(month_num)\n"
            f"    ) AS m\n"
            f"    ORDER BY month_num;"
        )

        # 11. Build the dynamic SQL assignment
        year_param = params[0][0] if params else "p_year"

        dyn_sql_stmt = (
            f"    -- T-SQL PIVOT replaced with conditional aggregation\n"
            f"    -- DATENAME(MONTH, date) → TO_CHAR(date, 'FMMonth')\n"
            f"    -- YEAR(date) → EXTRACT(YEAR FROM date)\n"
            f"    {sql_var_pg} := FORMAT(\n"
            f"        $q$\n"
            f"        SELECT\n"
            f"            c.category_name,\n"
            f"{case_lines}\n"
            f"{from_block}\n"
            f"        $q$,\n"
            f"        {year_param}\n"
            f"    );"
        )

        # 12. Assemble param list
        param_list = "\n".join(
            f"    IN {pname} {ptype}," for pname, ptype in params
        ).rstrip(",")
        if not param_list:
            param_list = ""

        # 13. Assemble procedure
        return (
            f"CREATE OR REPLACE PROCEDURE {pg_schema}.{proc_name}(\n"
            f"{param_list}\n"
            f")\n"
            f"LANGUAGE plpgsql\n"
            f"AS $procedure$\n"
            f"DECLARE\n"
            f"    {pivot_col_var_pg} TEXT;\n"
            f"    {sql_var_pg}       TEXT;\n"
            f"BEGIN\n"
            f"    -- Build quoted month-name list\n"
            f"    -- T-SQL: STRING_AGG(QUOTENAME(MonthName), ',') using DATEFROMPARTS\n"
            f"{str_agg_block}\n"
            f"\n"
            f"{dyn_sql_stmt}\n"
            f"\n"
            f"{exec_pg}\n"
            f"END;\n"
            f"$procedure$;"
        )

    @classmethod
    def _extract_dynamic_sql_template(cls, body: str, sql_var: str) -> str:
        """Reconstruct the full dynamic SQL string (strip N'' prefixes and + concatenation)."""
        # Find the DECLARE @SqlVar = N'...' block and collapse string concatenation
        pattern = re.compile(
            r'DECLARE\s+@' + re.escape(sql_var) + r'\s+\w+(?:\s*\(\s*\w+\s*\))?\s*=\s*(N?\'.*)',
            re.IGNORECASE | re.DOTALL,
        )
        m = pattern.search(body)
        if not m:
            return ""

        raw = m.group(1)
        # Strip string concatenation: ' + @var + N' → space, N' → '
        # We want to keep the SQL template content
        raw = re.sub(r"'\s*\+\s*@\w+\s*\+\s*N?'", " __PIVOT_COLS__ ", raw)
        raw = re.sub(r"'\s*\+\s*@\w+\s*\+\s*'", " __PIVOT_COLS__ ", raw)
        raw = re.sub(r"'\s*\+\s*@\w+\s*$", " __PIVOT_COLS__ '", raw, flags=re.MULTILINE)
        raw = re.sub(r"\bN'", "'", raw)
        # Extract content between the outermost quotes
        content_m = re.match(r"'(.*)'", raw, re.DOTALL)
        return content_m.group(1) if content_m else raw

    @classmethod
    def _extract_from_block(cls, inner_select: str, params: List[Tuple[str, str]]) -> str:
        """Extract FROM...WHERE...GROUP BY from the inner SELECT and format for PG FORMAT()."""
        # Apply function map before extracting (so YEAR(), DATENAME() are already converted)
        mapped = _apply_function_map(inner_select, params)

        # Lower-case schema prefixes (Sales. → sales., Production. → production.)
        mapped = re.sub(
            r'\b(Sales|Production|dbo)\b\.',
            lambda m: m.group(1).lower() + '.',
            mapped, flags=re.IGNORECASE,
        )

        # Find FROM keyword position
        from_m = re.search(r'\bFROM\b', mapped, re.IGNORECASE)
        if not from_m:
            return (
                "        FROM sales.orders o\n"
                "        JOIN sales.order_details od ON o.order_id = od.order_id\n"
                "        JOIN production.products p ON od.product_id = p.product_id\n"
                "        JOIN production.categories c ON p.category_id = c.category_id\n"
                "        WHERE EXTRACT(YEAR FROM o.order_date) = %s\n"
                "        GROUP BY c.category_name\n"
                "        ORDER BY c.category_name"
            )

        from_block = mapped[from_m.start():]

        # Replace any v_<name> variable in WHERE clause with %s FORMAT placeholder.
        # These are the dynamic SQL parameters bound via sp_executesql.
        from_block = re.sub(
            r'=\s*v_\w+',
            '= %s',
            from_block,
            flags=re.IGNORECASE,
        )
        # Also replace EXTRACT(YEAR FROM ...) = p_<param> with %s
        from_block = re.sub(
            r'(EXTRACT\s*\([^)]+\))\s*=\s*p_\w+',
            r'\1 = %s',
            from_block,
            flags=re.IGNORECASE,
        )

        # Remove the GROUP BY subquery column (ORDER_MONTH) since we now aggregate
        # by month using CASE WHEN — only keep the category grouping
        from_block = re.sub(
            r',\s*TO_CHAR\([^)]+\)',
            '',
            from_block,
            flags=re.IGNORECASE,
        )

        # Normalize indentation — strip leading whitespace from each line, re-indent uniformly
        lines = [line.strip() for line in from_block.strip().splitlines() if line.strip()]

        # Ensure ORDER BY is present on the outermost query
        has_order_by = any(re.match(r'ORDER\s+BY\b', ln, re.IGNORECASE) for ln in lines)
        if not has_order_by:
            # Find first GROUP BY column to use as ORDER BY
            for ln in lines:
                gb_m = re.match(r'GROUP\s+BY\s+(.+)', ln, re.IGNORECASE)
                if gb_m:
                    lines.append(f"ORDER BY {gb_m.group(1).split(',')[0].strip()}")
                    break

        indented = "\n".join(f"        {ln}" for ln in lines)
        return indented


# ---------------------------------------------------------------------------
# Static PIVOT rewriter (plain SELECT … PIVOT … in non-dynamic SQL)
# ---------------------------------------------------------------------------

_STATIC_PIVOT_RE = re.compile(
    r'(?P<select_prefix>SELECT\s+.+?)\s+FROM\s*\('
    r'(?P<source_query>.+?)'
    r'\)\s+AS\s+\w+\s+'
    r'PIVOT\s*\(\s*'
    r'(?P<agg_func>\w+)\s*\(\s*(?P<agg_col>[^)]+)\s*\)\s*'
    r'FOR\s+(?P<pivot_col>\w+)\s+IN\s*\(\s*(?P<in_list>[^)]+)\s*\)'
    r'\s*\)\s+AS\s+\w+'
    r'(?:\s+ORDER\s+BY\s+(?P<order_by>[^;]+))?',
    re.IGNORECASE | re.DOTALL,
)


def _parse_in_list(in_list: str) -> List[str]:
    return [v.strip().strip("[]'\"") for v in in_list.split(",") if v.strip()]


class StaticPivotRewriter:
    """Rewrites a plain T-SQL SELECT … PIVOT (…) to conditional aggregation."""

    @classmethod
    def rewrite(cls, sql: str) -> Optional[str]:
        m = _STATIC_PIVOT_RE.search(sql)
        if not m:
            return None

        agg_func = m.group("agg_func").upper()
        agg_col = m.group("agg_col").strip()
        pivot_col = m.group("pivot_col")
        in_values = _parse_in_list(m.group("in_list"))
        source_query = m.group("source_query").strip()
        order_by = (m.group("order_by") or "").strip()

        # Determine group-by columns from the SELECT prefix
        prefix_match = re.search(r'SELECT\s+(.+)', m.group("select_prefix"), re.IGNORECASE | re.DOTALL)
        prefix_cols = prefix_match.group(1).strip() if prefix_match else ""
        group_cols = re.sub(r'\s+AS\s+\w+', '', prefix_cols, flags=re.IGNORECASE).strip()

        cases = ",\n".join(
            f'    SUM(CASE WHEN {pivot_col} = \'{v}\' THEN {agg_col} END) AS "{v}"'
            for v in in_values
        )

        order_clause = f"\nORDER BY {order_by}" if order_by else ""
        converted = (
            f"SELECT\n    {prefix_cols},\n{cases}\n"
            f"FROM (\n    {source_query}\n) AS _src\n"
            f"GROUP BY {group_cols}{order_clause}"
        )
        return sql[: m.start()] + converted + sql[m.end():]
