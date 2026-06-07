"""
Module: sql_expression_converter.py
Purpose: Converts T-SQL expressions, function calls, and default values
         to PostgreSQL equivalents (inspired by dalibo/sqlserver2pgsql)
Domain: Transpilation
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

import re
from typing import Optional

from pydantic import BaseModel


class DefaultValueResult(BaseModel):
    value: str
    is_unsure: bool = False
    warnings: list[str] = []


_FUNCTION_CALL_RE = re.compile(r'''
    ([A-Z_][A-Z0-9_]*)\s*\(     # Function name + opening paren
    (                          # Capture group for arguments
        [^()]*(?:\([^()]*\)[^()]*)*  # Allow one level of nested parens
    )
    \)                          # Closing paren
''', re.IGNORECASE | re.VERBOSE)

_BRACKETED_LOGICAL_RE = re.compile(
    r'^\((.+)\)\s+(AND|OR)\s+\((.+)\)$', re.IGNORECASE
)
_UNBRACKETED_LOGICAL_RE = re.compile(
    r'^(.+?)\s+(AND|OR)\s+(.+?)$', re.IGNORECASE
)
_IDENTIFIER_BRACKET_RE = re.compile(r'\[(\w+)\]')
_CHECKSUM_RE = re.compile(r'CHECKSUM\s*\(', re.IGNORECASE)

TSQL_TO_PG_FUNCTIONS: dict[str, str] = {
    "GETDATE": "CURRENT_TIMESTAMP",
    "GETUTCDATE": "CURRENT_TIMESTAMP AT TIME ZONE 'UTC'",
    "CURRENT_TIMESTAMP": "CURRENT_TIMESTAMP",
    "CURRENT_USER": "CURRENT_USER",
    "SYSDATETIME": "CURRENT_TIMESTAMP",
    "SYSDATETIMEOFFSET": "CURRENT_TIMESTAMP AT TIME ZONE 'UTC'",
    "SYSUTCDATETIME": "CURRENT_TIMESTAMP AT TIME ZONE 'UTC'",
    "USER_NAME": "CURRENT_USER",
    "SESSION_USER": "SESSION_USER",
    "SYSTEM_USER": "SESSION_USER",
    "NEWID": "gen_random_uuid",
    "NEWSEQUENTIALID": "gen_random_uuid",
    "ISNULL": "COALESCE",
    "LEN": "LENGTH",
    "CHARINDEX": "STRPOS",
    "SUBSTRING": "SUBSTRING",
    "LEFT": "LEFT",
    "RIGHT": "RIGHT",
    "UPPER": "UPPER",
    "LOWER": "LOWER",
    "RTRIM": "RTRIM",
    "LTRIM": "LTRIM",
    "TRIM": "TRIM",
    "REPLACE": "REPLACE",
    "REPLICATE": "REPEAT",
    "REVERSE": "REVERSE",
    "STUFF": "OVERLAY",
    "SPACE": "REPEAT",
    "ABS": "ABS",
    "ROUND": "ROUND",
    "CEILING": "CEIL",
    "FLOOR": "FLOOR",
    "SCOPE_IDENTITY": "LASTVAL",
    "IDENT_CURRENT": "last_value",
    "DB_NAME": "CURRENT_DATABASE",
    "HOST_NAME": "pg_backend_pid",
    "DATEPART": "EXTRACT",
    "YEAR": "EXTRACT(YEAR FROM",
    "MONTH": "EXTRACT(MONTH FROM",
    "DAY": "EXTRACT(DAY FROM",
    "EOMONTH": "date_trunc('month', date) + interval '1 month - 1 day'",
    "FORMAT": "TO_CHAR",
    "STRING_AGG": "STRING_AGG",
    "STRING_SPLIT": "regexp_split_to_table",
    "ROW_NUMBER": "ROW_NUMBER",
    "RANK": "RANK",
    "DENSE_RANK": "DENSE_RANK",
    "NTILE": "NTILE",
    "LEAD": "LEAD",
    "LAG": "LAG",
    "FIRST_VALUE": "FIRST_VALUE",
    "LAST_VALUE": "LAST_VALUE",
    "IIF": "CASE WHEN",
    "CHOOSE": "CASE",
    "PATINDEX": "POSITION",
    "JSON_VALUE": "jsonb_extract_path_text",
    "JSON_QUERY": "jsonb_extract_path",
    "OPENJSON": "jsonb_to_recordset",
    "NULLIF": "NULLIF",
    "COALESCE": "COALESCE",
    "CONVERT": "CAST",
    "TRY_CAST": "CAST",
    "TRY_CONVERT": "CAST",
    "PARSE": "CAST",
    "SUSER_SNAME": "CURRENT_USER",
    "ORIGINAL_LOGIN": "CURRENT_USER",
    "APP_NAME": "current_setting('application_name')",
    "GETANSINULL": "CAST(1 AS BOOLEAN)",
    "HOST_ID": "pg_backend_pid",
    "OBJECT_NAME": "pg_class.relname",
    "OBJECT_ID": "(SELECT oid FROM pg_class WHERE relname = ",
    "COL_LENGTH": "information_schema.character_maximum_length",
    "COL_NAME": "information_schema.column_name",
}


class TsqlExpressionConverter:
    """Converts T-SQL expressions, functions, and default values to PostgreSQL.

    Based on patterns from the reference sqlserver2pgsql Perl tool,
    but reimplemented for Python with IR-based architecture.
    """

    # Mapping of T-SQL date parts to PostgreSQL date_part strings
    DATEPART_MAP: dict[str, str] = {
        "YEAR": "YEAR",
        "YY": "YEAR",
        "YYYY": "YEAR",
        "QUARTER": "QUARTER",
        "QQ": "QUARTER",
        "Q": "QUARTER",
        "MONTH": "MONTH",
        "MM": "MONTH",
        "M": "MONTH",
        "DAYOFYEAR": "DOY",
        "DY": "DOY",
        "Y": "DOY",
        "DAY": "DAY",
        "DD": "DAY",
        "D": "DAY",
        "WEEK": "WEEK",
        "WK": "WEEK",
        "WW": "WEEK",
        "WEEKDAY": "DOW",
        "DW": "DOW",
        "HOUR": "HOUR",
        "HH": "HOUR",
        "MINUTE": "MINUTE",
        "MI": "MINUTE",
        "N": "MINUTE",
        "SECOND": "SECOND",
        "SS": "SECOND",
        "S": "SECOND",
        "MILLISECOND": "MILLISECOND",
        "MS": "MILLISECOND",
        "MICROSECOND": "MICROSECOND",
        "MCS": "MICROSECOND",
        "NANOSECOND": "NANOSECOND",
        "NS": "NANOSECOND",
    }

    # Style codes for CONVERT to known formats
    CONVERT_STYLES: dict[int, str] = {
        1: "YYYY-MM-DD HH:MI:SS",       # 1 = 101 US style
        101: "YYYY-MM-DD",
        102: "YYYY.MM.DD",
        103: "DD/MM/YYYY",
        104: "DD.MM.YYYY",
        105: "DD-MM-YYYY",
        106: "DD MON YYYY",
        107: "MON DD, YYYY",
        108: "HH:MI:SS",
        109: "MON DD YYYY HH:MI:SS:MMM",
        110: "MM-DD-YYYY",
        111: "YYYY/MM/DD",
        112: "YYYYMMDD",
        120: "YYYY-MM-DD HH:MI:SS",
        121: "YYYY-MM-DD HH:MI:SS.MMM",
        126: "YYYY-MM-DDTHH:MI:SS.MMM",
    }

    @classmethod
    def convert_function_call(cls, expression: str) -> str:
        """Convert a single T-SQL function call to PostgreSQL equivalent.

        Handles:
        - ISNULL(a, b) -> COALESCE(a, b)
        - GETDATE() -> CURRENT_TIMESTAMP
        - CHARINDEX(sub, str) -> STRPOS(str, sub)
        - DATEPART(part, date) -> EXTRACT(part FROM date)
        - DATEADD(part, n, date) -> date + INTERVAL 'n part'
        - DATEDIFF(part, d1, d2) -> EXTRACT(EPOCH FROM (d2 - d1)) / ...
        - CONVERT(type, expr[, style]) -> CAST(expr AS type)
        - SPACE(n) -> REPEAT(' ', n)
        """
        expr = expression.strip()

        # ISNULL(a, b) -> COALESCE(a, b)
        if m := re.match(r'ISNULL\s*\((.+)\)', expr, re.IGNORECASE):
            args = cls._split_args(m.group(1))
            return f"COALESCE({args[0]}, {args[1]})" if len(args) >= 2 else expr

        # CHARINDEX(sub, str[, start]) -> STRPOS(str, sub)
        if m := re.match(r'CHARINDEX\s*\((.+)\)', expr, re.IGNORECASE):
            args = cls._split_args(m.group(1))
            if len(args) >= 2:
                result = f"STRPOS({args[1]}, {args[0]})"
                if len(args) >= 3:
                    result = f"STRPOS(SUBSTRING({args[1]}, {args[2]}), {args[0]}) + {args[2]} - 1"
                return result
            return expr

        # PATINDEX('%pattern%', expr) - SQL Server uses LIKE patterns with % _ [charclass]
        # PostgreSQL: convert LIKE pattern to regex and use regexp_match for position
        if m := re.match(r'PATINDEX\s*\((.+)\)', expr, re.IGNORECASE):
            args = cls._split_args(m.group(1))
            if len(args) >= 2:
                pattern = args[0].strip()
                string_expr = args[1]
                # Convert SQL LIKE pattern to POSIX regex pattern
                like_to_regex = pattern
                like_to_regex = like_to_regex.lstrip("'").rstrip("'")
                like_to_regex = re.escape(like_to_regex)
                like_to_regex = like_to_regex.replace(r'%', '.*')
                like_to_regex = like_to_regex.replace(r'_', '.')
                like_to_regex = like_to_regex.replace(r'\[', '[')
                like_to_regex = like_to_regex.replace(r'\]', ']')
                like_to_regex = f"'{like_to_regex}'"
                return f"(CASE WHEN {string_expr} ~ {like_to_regex} THEN LENGTH(REGEXP_MATCHES({string_expr}, {like_to_regex})[1]) - 1 ELSE 0 END) /* WARNING: PATINDEX LIKE pattern -> regex */"
            return expr

        # DATEPART(part, date) -> EXTRACT(part FROM date)
        if m := re.match(r'DATEPART\s*\((.+)\)', expr, re.IGNORECASE):
            args = cls._split_args(m.group(1))
            if len(args) >= 2:
                pg_part = cls.DATEPART_MAP.get(args[0].upper().strip(), args[0].strip())
                return f"EXTRACT({pg_part} FROM {args[1]})"
            return expr

        # DATEADD(part, n, date) -> date + INTERVAL 'n part'
        if m := re.match(r'DATEADD\s*\((.+)\)', expr, re.IGNORECASE):
            args = cls._split_args(m.group(1))
            if len(args) >= 3:
                pg_part = cls._datepart_to_interval(args[0].strip())
                return f"{args[2]} + INTERVAL '{args[1]} {pg_part}'"
            return expr

        # DATEDIFF(part, d1, d2) -> various PG constructs
        if m := re.match(r'DATEDIFF\s*\((.+)\)', expr, re.IGNORECASE):
            args = cls._split_args(m.group(1))
            if len(args) >= 3:
                return cls._convert_datediff(args[0].strip(), args[1], args[2])
            return expr

        # CONVERT(type, expr[, style]) -> CAST(expr AS type)
        if m := re.match(r'CONVERT\s*\((.+)\)', expr, re.IGNORECASE):
            args = cls._split_args(m.group(1))
            if len(args) >= 2:
                pg_type = cls._convert_type_name(args[0].strip())
                if len(args) >= 3:
                    return f"CAST({args[1]} AS {pg_type})"
                return f"CAST({args[1]} AS {pg_type})"
            return expr

        # IIF(cond, t, f) -> CASE WHEN cond THEN t ELSE f END
        if m := re.match(r'IIF\s*\((.+)\)', expr, re.IGNORECASE):
            args = cls._split_args(m.group(1))
            if len(args) >= 3:
                return f"CASE WHEN {args[0]} THEN {args[1]} ELSE {args[2]} END"
            return expr

        # SPACE(n) -> REPEAT(' ', n)
        if m := re.match(r'SPACE\s*\((.+)\)', expr, re.IGNORECASE):
            return f"REPEAT(' ', {m.group(1)})"

        # STUFF(str, start, length, replace_str) -> OVERLAY(str PLACING replace_str FROM start FOR length)
        if m := re.match(r'STUFF\s*\((.+)\)', expr, re.IGNORECASE):
            args = cls._split_args(m.group(1))
            if len(args) >= 4:
                return f"OVERLAY({args[0]} PLACING {args[3]} FROM {args[1]} FOR {args[2]})"
            return expr

        # CHOOSE(idx, val1, val2, ...) -> CASE idx WHEN 1 THEN val1 WHEN 2 THEN val2 ... ELSE NULL END
        if m := re.match(r'CHOOSE\s*\((.+)\)', expr, re.IGNORECASE):
            args = cls._split_args(m.group(1))
            if len(args) >= 2:
                idx_expr = args[0]
                when_parts = []
                for i, val in enumerate(args[1:], 1):
                    when_parts.append(f"WHEN {i} THEN {val}")
                when_clauses = " ".join(when_parts)
                return f"CASE {idx_expr} {when_clauses} END"
            return expr

        # STRING_SPLIT(str, delim) -> unnest(string_to_array(str, delim))
        if m := re.match(r'STRING_SPLIT\s*\((.+)\)', expr, re.IGNORECASE):
            args = cls._split_args(m.group(1))
            if len(args) >= 2:
                return f"UNNEST(STRING_TO_ARRAY({args[0]}, {args[1]}))"
            return expr

        # TRY_CAST(expr AS type) -> CAST but with warning comment
        # PostgreSQL doesn't have safe casting built-in
        if m := re.match(r'TRY_CAST\s*\((.+)\)', expr, re.IGNORECASE):
            inner = m.group(1).strip()
            return f"CAST({inner}) /* WARNING: TRY_CAST returns NULL on error, CAST will throw */"

        # TRY_CONVERT(type, expr[, style]) -> CAST with warning
        if m := re.match(r'TRY_CONVERT\s*\((.+)\)', expr, re.IGNORECASE):
            args = cls._split_args(m.group(1))
            if len(args) >= 2:
                pg_type = cls._convert_type_name(args[0].strip())
                return f"CAST({args[1]} AS {pg_type}) /* WARNING: TRY_CONVERT returns NULL on error, CAST will throw */"
            return expr

        # PARSE(string AS type) -> CAST
        if m := re.match(r'PARSE\s*\((.+)\)', expr, re.IGNORECASE):
            inner = m.group(1).strip()
            inner = re.sub(r'\s+AS\s+', ' AS ', inner, flags=re.IGNORECASE)
            return f"CAST({inner}) /* WARNING: PARSE culture setting not preserved */"

        # OPENJSON(json) -> jsonb_array_elements
        if m := re.match(r'OPENJSON\s*\((.+)\)', expr, re.IGNORECASE):
            args = cls._split_args(m.group(1))
            if len(args) >= 1:
                if len(args) >= 2:
                    return f"JSONB_TO_RECORDSET({args[0]}) /* WITH clause may need manual adjustment */"
                return f"JSONB_ARRAY_ELEMENTS({args[0]})"
            return expr

        # CHECKSUM(expr1, expr2, ...) -> no direct equivalent, add warning
        if m := re.match(r'CHECKSUM\s*\((.+)\)', expr, re.IGNORECASE):
            return "0 /* WARNING: CHECKSUM() has no PostgreSQL equivalent */"

        # BINARY_CHECKSUM(*) -> no direct equivalent (must avoid function name in output to prevent recursion)
        if re.match(r'BINARY_CHECKSUM\s*\(', expr, re.IGNORECASE):
            return "0 /* WARNING: BINARY_CHECKSUM has no PostgreSQL equivalent */"

        # CHECKSUM_AGG(expr) -> no direct equivalent
        if m := re.match(r'CHECKSUM_AGG\s*\((.+)\)', expr, re.IGNORECASE):
            return "0 /* WARNING: CHECKSUM_AGG has no direct PostgreSQL equivalent */"

        # OBJECT_NAME(object_id) -> query pg_class
        if m := re.match(r'OBJECT_NAME\s*\((.+)\)', expr, re.IGNORECASE):
            args = cls._split_args(m.group(1))
            if len(args) >= 1:
                return f"(SELECT relname FROM pg_class WHERE oid = {args[0]}) /* OBJECT_NAME conversion */"
            return expr

        # OBJECT_ID('table_name') -> query pg_class
        if m := re.match(r'OBJECT_ID\s*\((.+)\)', expr, re.IGNORECASE):
            args = cls._split_args(m.group(1))
            if len(args) >= 1:
                return f"(SELECT oid FROM pg_class WHERE relname = {args[0]}) /* OBJECT_ID conversion */"
            return expr

        # COL_LENGTH('table', 'column') -> query information_schema
        if m := re.match(r'COL_LENGTH\s*\((.+)\)', expr, re.IGNORECASE):
            args = cls._split_args(m.group(1))
            if len(args) >= 2:
                return f"(SELECT character_maximum_length FROM information_schema.columns WHERE table_name = {args[0]} AND column_name = {args[1]}) /* COL_LENGTH conversion */"
            return expr

        # COL_NAME(table_id, column_id) -> query pg_attribute
        if m := re.match(r'COL_NAME\s*\((.+)\)', expr, re.IGNORECASE):
            args = cls._split_args(m.group(1))
            if len(args) >= 2:
                return f"(SELECT attname FROM pg_attribute WHERE attrelid = {args[0]} AND attnum = {args[1]}) /* COL_NAME conversion */"
            return expr

        # ORIGINAL_LOGIN() -> CURRENT_USER with warning
        if m := re.match(r'ORIGINAL_LOGIN\s*\(\s*\)', expr, re.IGNORECASE):
            return "CURRENT_USER /* WARNING: ORIGINAL_LOGIN impersonation context has no direct PG equivalent */"

        # APP_NAME() -> current_setting
        if m := re.match(r'APP_NAME\s*\(\s*\)', expr, re.IGNORECASE):
            return "CURRENT_SETTING('application_name', true) /* APP_NAME conversion */"

        # HOST_ID() -> pg_backend_pid with warning
        if m := re.match(r'HOST_ID\s*\(\s*\)', expr, re.IGNORECASE):
            return "PG_BACKEND_PID()::TEXT /* WARNING: function has no exact PG equivalent */"

        # GETANSINULL() -> boolean true
        if m := re.match(r'GETANSINULL\s*\(\s*\)', expr, re.IGNORECASE):
            return "TRUE /* GETANSINULL conversion: ANSI NULL behavior */"

        # SUSER_SNAME() -> CURRENT_USER
        if m := re.match(r'SUSER_SNAME\s*\(\s*\)', expr, re.IGNORECASE):
            return "CURRENT_USER"

        # FORMAT(value, format_string[, culture]) -> TO_CHAR with format conversion
        if m := re.match(r'FORMAT\s*\((.+)\)', expr, re.IGNORECASE):
            args = cls._split_args(m.group(1))
            if len(args) >= 2:
                value = args[0].strip()
                fmt = args[1].strip()
                culture = args[2].strip() if len(args) >= 3 else None
                pg_fmt = cls._convert_format_string(fmt, culture)
                return f"TO_CHAR({value}, {pg_fmt}) /* FORMAT conversion */"
            return expr

        # NUMBER_TO_STR(value, fmt[, locale]) - SQLGlot postgres output for FORMAT
        if m := re.match(r'NUMBER_TO_STR\s*\((.+)\)', expr, re.IGNORECASE):
            args = cls._split_args(m.group(1))
            if len(args) >= 2:
                value = args[0].strip()
                fmt = args[1].strip()
                culture = args[2].strip() if len(args) >= 3 else None
                pg_fmt = cls._convert_format_string(fmt, culture)
                return f"TO_CHAR({value}, {pg_fmt}) /* FORMAT conversion */"
            return expr

        # GETDATE(), GETUTCDATE(), SYSDATETIME(), SYSUTCDATETIME(), NEWID(), etc. - zero-arg functions
        zero_arg_funcs = {
            'GETDATE': 'CURRENT_TIMESTAMP',
            'GETUTCDATE': "CURRENT_TIMESTAMP AT TIME ZONE 'UTC'",
            'SYSDATETIME': 'CURRENT_TIMESTAMP',
            'SYSUTCDATETIME': "CURRENT_TIMESTAMP AT TIME ZONE 'UTC'",
            'NEWID': 'GEN_RANDOM_UUID()',
            'SCOPE_IDENTITY': 'LASTVAL()',
            'DB_NAME': 'CURRENT_DATABASE()',
            'HOST_NAME': "INET_SERVER_ADDR()::TEXT",
            'ROW_NUMBER': 'ROW_NUMBER()',
            'RANK': 'RANK()',
            'DENSE_RANK': 'DENSE_RANK()',
        }
        if m := re.match(r'([A-Z_][A-Z0-9_]*)\s*\(\s*\)', expr, re.IGNORECASE):
            func_name = m.group(1).upper()
            if func_name in zero_arg_funcs:
                return zero_arg_funcs[func_name]
            return TSQL_TO_PG_FUNCTIONS.get(func_name, expr)

        # USER_NAME(), CURRENT_USER, SESSION_USER
        if m := re.match(r'(USER_NAME|SESSION_USER|SYSTEM_USER|CURRENT_USER)\s*\(\s*\)', expr, re.IGNORECASE):
            func_name = m.group(1).upper()
            return TSQL_TO_PG_FUNCTIONS.get(func_name, expr)

        # @@IDENTITY -> LASTVAL()
        if expr.upper().strip() == '@@IDENTITY':
            return "LASTVAL()"

        # @@ROWCOUNT -> GET DIAGNOSTICS (for PL/pgSQL context)
        if expr.upper().strip() == '@@ROWCOUNT':
            return "0 /* @@ROWCOUNT - needs GET DIAGNOSTICS in PL/pgSQL context */"

        # @@ERROR -> GET STACKED DIAGNOSTICS
        if expr.upper().strip() == '@@ERROR':
            return "GET STACKED DIAGNOSTICS"

        # ROW_COUNT (from preprocessing) -> needs manual handling
        if expr.upper().strip() == 'ROW_COUNT':
            return "0 /* @@ROWCOUNT - needs GET DIAGNOSTICS in PL/pgSQL context */"

        return expr

    @classmethod
    def convert_default_value(cls, value: str, column_type: Optional[str] = None) -> DefaultValueResult:
        """Convert a T-SQL default value to PostgreSQL.

        Handles:
        - Numeric literals -> unchanged
        - NULL -> NULL (without quotes)
        - N'string' -> 'string' (strip N prefix)
        - String 'value' -> 'value'
        - Function calls -> converted
        - Boolean 0/1 -> false/true
        """
        stripped = value.strip()

        # NULL without quotes
        if stripped.upper() == 'NULL':
            return DefaultValueResult(value='NULL')

        # Numeric literal: (42), 42, (3.14)
        if m := re.match(r'^\(?(\d+(?:\.\d+)?)\)?$', stripped):
            num_val = m.group(1)
            if column_type and column_type.upper() in ('BIT', 'BOOLEAN'):
                if num_val == '0':
                    return DefaultValueResult(value='false')
                if num_val == '1':
                    return DefaultValueResult(value='true')
                return DefaultValueResult(
                    value=num_val,
                    warnings=[f"Boolean column default value '{num_val}' is not 0 or 1"],
                )
            return DefaultValueResult(value=num_val)

        # N'string' -> 'string'
        if m := re.match(r"^N'(.*)'$", stripped):
            return DefaultValueResult(value=f"'{m.group(1)}'")

        # 'string'
        if m := re.match(r"^'(.*)'$", stripped):
            return DefaultValueResult(value=f"'{m.group(1)}'")

        # (expression) - unwrap parens
        if m := re.match(r'^\((.+)\)$', stripped):
            inner = cls.convert_default_value(m.group(1), column_type)
            return DefaultValueResult(
                value=inner.value,
                is_unsure=inner.is_unsure,
                warnings=inner.warnings,
            )

        # Function call - try to convert
        converted = cls.convert_function_call(stripped)
        if converted != stripped:
            return DefaultValueResult(value=converted, is_unsure=True)

        # Unknown expression - pass through but mark unsure
        return DefaultValueResult(value=stripped, is_unsure=True)

    @classmethod
    def convert_expression(cls, expression: str) -> str:
        """Convert a T-SQL expression containing multiple elements to PostgreSQL.

        Handles:
        - Identifier bracketing: [name] -> "name" or name
        - Function calls within broader expressions
        - Logical operators AND/OR at depth 0 (not inside parentheses)
        - String concatenation: + -> ||
        """
        expr = expression.strip()

        if not expr:
            return expr

        # Convert identifiers [name] -> "name"
        if '[' in expr:
            expr = _IDENTIFIER_BRACKET_RE.sub(r'"\1"', expr)

        # Convert function calls within the expression
        # Work from outer to inner to handle nesting
        expr = cls._convert_all_functions(expr)

        # Handle logical AND/OR at depth 0 (not inside parenthesized expressions)
        # This must happen AFTER function conversion to avoid splitting on
        # AND/OR inside window frames or other parenthesized syntax
        expr = cls._split_logical_at_depth_zero(expr)

        # Convert string concatenation: + -> || when string literals are involved
        expr = cls._convert_string_concat(expr)

        return expr

    @classmethod
    def _split_logical_at_depth_zero(cls, expr: str) -> str:
        """Split logical AND/OR operators that are at depth 0 (not inside parens)."""
        in_string = False
        string_char = None
        depth = 0
        i = 0
        while i < len(expr):
            ch = expr[i]
            if in_string:
                if ch == string_char and (i > 0 and expr[i - 1] != '\\'):
                    in_string = False
            elif ch in ("'", '"'):
                in_string = True
                string_char = ch
            elif ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
            elif depth == 0 and i + 2 < len(expr):
                # Check for OR at depth 0
                if expr[i:i+2].upper() == 'OR' and cls._is_word_boundary(expr, i, 2):
                    lhs = expr[:i].strip()
                    rhs = expr[i+2:].strip()
                    if lhs and rhs:
                        return f"({cls.convert_expression(lhs)}) OR ({cls.convert_expression(rhs)})"
                # Check for AND at depth 0
                if expr[i:i+3].upper() == 'AND' and cls._is_word_boundary(expr, i, 3):
                    lhs = expr[:i].strip()
                    rhs = expr[i+3:].strip()
                    if lhs and rhs:
                        return f"({cls.convert_expression(lhs)}) AND ({cls.convert_expression(rhs)})"
            i += 1
        return expr

    @staticmethod
    def _is_word_boundary(text: str, pos: int, length: int) -> bool:
        """Check if the word at position has word boundaries on both sides."""
        before_ok = pos == 0 or not text[pos - 1].isalnum()
        after_ok = pos + length >= len(text) or not text[pos + length].isalnum()
        return before_ok and after_ok

    @classmethod
    def _convert_all_functions(cls, expr: str) -> str:
        """Recursively convert all function calls in an expression."""
        # This handles function nesting by repeatedly applying conversions
        prev = None
        current = expr
        max_iterations = 20  # prevent infinite loops
        iteration = 0
        while current != prev and iteration < max_iterations:
            prev = current
            current = cls._convert_function_layer(current)
            iteration += 1
        return current

    @classmethod
    def _convert_function_layer(cls, expr: str) -> str:
        """Convert one layer of function calls."""
        def replace_func(m: re.Match) -> str:
            full_call = m.group(0)
            return cls.convert_function_call(full_call)

        return _FUNCTION_CALL_RE.sub(replace_func, expr)

    @staticmethod
    def _convert_format_string(fmt_str: str, culture: str | None = None) -> str:
        """Convert SQL Server FORMAT format string to PostgreSQL TO_CHAR format."""
        fmt = fmt_str.strip().strip("'\"")
        upper = fmt.upper()

        if upper == 'C':
            return "'FM$999,999,990.00' /* CURRENCY */"
        if upper in ('D', 'F'):
            return "'FMMonth DD, YYYY' /* LONG DATE */"
        if upper in ('T', 't'):
            return "'HH24:MI:SS' /* SHORT TIME */"
        if upper in ('U', 'u'):
            return "'YYYY-MM-DD HH24:MI:SS UTC' /* UNIVERSAL */"
        if upper == 'G':
            return "'FMMM/DD/YYYY HH24:MI:SS' /* GENERAL DATE/TIME */"

        pg_fmt = fmt
        pg_fmt = pg_fmt.replace('yyyy', 'YYYY')
        pg_fmt = pg_fmt.replace('yy', 'YY')
        pg_fmt = pg_fmt.replace('MM', 'MM')
        pg_fmt = pg_fmt.replace('dd', 'DD')
        pg_fmt = pg_fmt.replace('HH', 'HH24')
        pg_fmt = pg_fmt.replace('mm', 'MI')
        pg_fmt = pg_fmt.replace('ss', 'SS')
        return f"'{pg_fmt}'"

    @staticmethod
    def _convert_string_concat(expr: str) -> str:
        """Convert T-SQL string concatenation (+) to PostgreSQL (||).

        Heuristic: only convert '+' when at least one adjacent operand
        is a string literal (single-quoted). Leave arithmetic '+' unchanged.
        """
        if "'" not in expr or '+' not in expr:
            return expr

        # Only convert + that appears directly adjacent to a string literal
        # Pattern: 'string' + expr or expr + 'string'
        # This avoids converting arithmetic + like 1 + 2 or col + 1
        def replace_concat(m):
            return m.group(0).replace('+', '||')

        # Case 1: 'string_literal' + something
        result = re.sub(r"'(?:[^'\\]|\\.)*'\s*\+", replace_concat, expr)
        # Case 2: something + 'string_literal'
        result = re.sub(r"\+\s*'(?:[^'\\]|\\.)*'", replace_concat, result)

        return result

    @staticmethod
    def _split_args(args_str: str) -> list[str]:
        """Split function arguments respecting quoted strings and nested parens.

        Handles cases like: 'str, with comma', func(a, b), etc.
        """
        args = []
        depth = 0
        current = ''
        in_string = False
        string_char = ''
        i = 0
        while i < len(args_str):
            ch = args_str[i]
            if in_string:
                current += ch
                if ch == string_char and (i == 0 or args_str[i - 1] != '\\'):
                    in_string = False
            elif ch in ('"', "'", 'N'):
                # Handle N'...' prefix
                if ch == 'N' and i + 1 < len(args_str) and args_str[i + 1] == "'":
                    current += ch
                    in_string = True
                    string_char = "'"
                elif ch in ('"', "'"):
                    in_string = True
                    string_char = ch
                    current += ch
                else:
                    current += ch
            elif ch == '(':
                depth += 1
                current += ch
            elif ch == ')':
                depth -= 1
                current += ch
            elif ch == ',' and depth == 0:
                args.append(current.strip())
                current = ''
            else:
                current += ch
            i += 1
        if current.strip():
            args.append(current.strip())
        return args

    @staticmethod
    def _convert_type_name(tsql_type: str) -> str:
        """Convert a T-SQL type name (from CONVERT) to PostgreSQL."""
        upper = tsql_type.upper().strip()
        mapping = {
            'NVARCHAR': 'VARCHAR',
            'VARCHAR': 'VARCHAR',
            'NCHAR': 'CHAR',
            'CHAR': 'CHAR',
            'INT': 'INTEGER',
            'INTEGER': 'INTEGER',
            'BIGINT': 'BIGINT',
            'SMALLINT': 'SMALLINT',
            'TINYINT': 'SMALLINT',
            'BIT': 'BOOLEAN',
            'DECIMAL': 'NUMERIC',
            'NUMERIC': 'NUMERIC',
            'FLOAT': 'DOUBLE PRECISION',
            'REAL': 'REAL',
            'MONEY': 'NUMERIC',
            'SMALLMONEY': 'NUMERIC',
            'DATETIME': 'TIMESTAMP',
            'DATETIME2': 'TIMESTAMP',
            'SMALLDATETIME': 'TIMESTAMP',
            'DATE': 'DATE',
            'TIME': 'TIME',
            'DATETIMEOFFSET': 'TIMESTAMPTZ',
            'UNIQUEIDENTIFIER': 'UUID',
            'TEXT': 'TEXT',
            'NTEXT': 'TEXT',
            'IMAGE': 'BYTEA',
            'BINARY': 'BYTEA',
            'VARBINARY': 'BYTEA',
            'TIMESTAMP': 'BYTEA',
            'ROWVERSION': 'BYTEA',
            'XML': 'XML',
        }
        # Strip any size qualifier like VARCHAR(50) -> VARCHAR
        base = re.split(r'[\(\s]', upper)[0]
        pg_type = mapping.get(base, upper)

        # Re-apply the qualifier if present
        if m := re.match(r'(\w+)\((.+)\)', tsql_type.strip()):
            qual = m.group(2)
            if pg_type == 'VARCHAR':
                return f"VARCHAR({qual})"
            return f"{pg_type}({qual})"
        return pg_type

    @staticmethod
    def _convert_datediff(part: str, date1: str, date2: str) -> str:
        """Convert T-SQL DATEDIFF to PostgreSQL expression."""
        part_upper = part.upper().strip()

        if part_upper in ('DAY', 'DD', 'D'):
            return f"({date2}::date - {date1}::date)"
        if part_upper in ('HOUR', 'HH'):
            return f"EXTRACT(EPOCH FROM ({date2} - {date1})) / 3600"
        if part_upper in ('MINUTE', 'MI', 'N'):
            return f"EXTRACT(EPOCH FROM ({date2} - {date1})) / 60"
        if part_upper in ('SECOND', 'SS', 'S'):
            return f"EXTRACT(EPOCH FROM ({date2} - {date1}))"
        if part_upper in ('MILLISECOND', 'MS'):
            return f"EXTRACT(EPOCH FROM ({date2} - {date1})) * 1000"
        if part_upper in ('YEAR', 'YY', 'YYYY'):
            return f"EXTRACT(YEAR FROM {date2}) - EXTRACT(YEAR FROM {date1})"
        if part_upper in ('MONTH', 'MM', 'M'):
            return (
                f"(EXTRACT(YEAR FROM {date2}) - EXTRACT(YEAR FROM {date1})) * 12"
                f" + (EXTRACT(MONTH FROM {date2}) - EXTRACT(MONTH FROM {date1}))"
            )
        if part_upper in ('WEEK', 'WK', 'WW'):
            return f"(({date2}::date - {date1}::date) / 7)"
        return f"({date2} - {date1})"

    @staticmethod
    def _datepart_to_interval(part: str) -> str:
        """Convert T-SQL DATEPART name to PostgreSQL interval unit."""
        part_upper = part.upper().strip()
        mapping = {
            'YEAR': 'YEAR', 'YY': 'YEAR', 'YYYY': 'YEAR',
            'MONTH': 'MONTH', 'MM': 'MONTH', 'M': 'MONTH',
            'DAY': 'DAY', 'DD': 'DAY', 'D': 'DAY',
            'HOUR': 'HOUR', 'HH': 'HOUR',
            'MINUTE': 'MINUTE', 'MI': 'MINUTE', 'N': 'MINUTE',
            'SECOND': 'SECOND', 'SS': 'SECOND', 'S': 'SECOND',
            'WEEK': 'WEEK', 'WK': 'WEEK', 'WW': 'WEEK',
            'QUARTER': 'MONTH',  # approximate - 3 months
            'QQ': 'MONTH', 'Q': 'MONTH',
            'MILLISECOND': 'MILLISECONDS',
            'MS': 'MILLISECONDS',
            'MICROSECOND': 'MICROSECONDS',
            'MCS': 'MICROSECONDS',
        }
        return mapping.get(part_upper, part_upper)
