"""
Module: domains/transpilation/converters/cursor_handler.py
Purpose: Handle T-SQL CURSOR operations and convert to PostgreSQL REFCURSOR patterns.

T-SQL CURSOR Pattern:
    DECLARE @cursor CURSOR
    FOR SELECT id, name FROM users WHERE active = 1;
    OPEN @cursor;
    FETCH NEXT FROM @cursor INTO @id, @name;
    WHILE @@FETCH_STATUS = 0
    BEGIN
        -- Process row
        FETCH NEXT FROM @cursor INTO @id, @name;
    END
    CLOSE @cursor;
    DEALLOCATE @cursor;

PostgreSQL REFCURSOR Pattern (using stored procedure):
    CREATE OR REPLACE FUNCTION get_users_cursor(p_cursor REFCURSOR)
    RETURNS REFCURSOR AS $$
    BEGIN
        OPEN p_cursor FOR SELECT id, name FROM users WHERE active = 1;
        RETURN p_cursor;
    END;
    $$ LANGUAGE plpgsql;

    -- Or using cursor in function body:
    FOR r IN SELECT id, name FROM users WHERE active = 1 LOOP
        -- Process row r.id, r.name
    END LOOP;

Author: Claude Code (Haiku 4.5)
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CursorDefinition:
    """Parsed CURSOR definition."""

    cursor_name: str = ""
    query: str = ""
    loop_variable: str = ""
    fetch_into_vars: List[str] = field(default_factory=list)
    has_fetch_status_check: bool = False
    uses_refcursor: bool = False


@dataclass
class ConversionResult:
    """Result of CURSOR conversion."""

    sql: str
    success: bool = False
    warnings: List[str] = field(default_factory=list)
    conversion_type: str = ""  # "refcursor_function" | "for_loop" | "manual"


class CursorHandler:
    """Handles T-SQL CURSOR operations."""

    _CURSOR_DECLARE = re.compile(
        r"DECLARE\s+(@?\w+)\s+(?:AS\s+)?(?:CURSOR|REFCURSOR)(?:\s+FOR\s+(.+?))?(?=;|$)",
        re.IGNORECASE | re.DOTALL,
    )

    _CURSOR_FOR = re.compile(
        r"(?:FOR|OPEN\s+.*?FOR)\s+(.+?)(?=;|FETCH|CLOSE|$)",
        re.IGNORECASE | re.DOTALL,
    )

    _OPEN_FOR = re.compile(
        r"OPEN\s+(?:@?\w+)\s+FOR\s+(.+?)(?=;|FETCH|CLOSE|$)",
        re.IGNORECASE | re.DOTALL,
    )

    _FETCH_INTO = re.compile(
        r"FETCH\s+(?:NEXT\s+)?FROM\s+(@?\w+)\s+INTO\s+(.*?)(?=;|WHILE|FETCH|END)",
        re.IGNORECASE | re.DOTALL,
    )

    _FETCH_STATUS = re.compile(
        r"@@FETCH_STATUS\s*=\s*0",
        re.IGNORECASE,
    )

    _CURSOR_LOOP_BODY = re.compile(
        r"WHILE\s+.*?@@FETCH_STATUS.*?\s+BEGIN\s+(.*?)\s+END",
        re.IGNORECASE | re.DOTALL,
    )

    @staticmethod
    def parse_cursor(sql: str) -> Optional[CursorDefinition]:
        """Parse a CURSOR declaration and usage.

        Returns:
            CursorDefinition with extracted components.
        """
        cursor = CursorDefinition()

        # Parse DECLARE ... CURSOR
        declare_match = CursorHandler._CURSOR_DECLARE.search(sql)
        if not declare_match:
            return None

        cursor.cursor_name = declare_match.group(1).strip()
        if declare_match.group(2):
            cursor.query = declare_match.group(2).strip()

        # Parse FOR SELECT query
        if not cursor.query:
            for_match = CursorHandler._CURSOR_FOR.search(sql)
            if for_match:
                cursor.query = for_match.group(1).strip()

        # If still no query, try OPEN ... FOR pattern
        if not cursor.query:
            open_match = CursorHandler._OPEN_FOR.search(sql)
            if open_match:
                cursor.query = open_match.group(1).strip()

        # Parse FETCH INTO
        fetch_match = CursorHandler._FETCH_INTO.search(sql)
        if fetch_match:
            vars_str = fetch_match.group(2).strip()
            cursor.fetch_into_vars = [v.strip() for v in vars_str.split(",")]

        # Check for FETCH_STATUS loop
        if CursorHandler._FETCH_STATUS.search(sql):
            cursor.has_fetch_status_check = True

        # Check for REFCURSOR usage
        if "REFCURSOR" in sql.upper():
            cursor.uses_refcursor = True

        return cursor

    @staticmethod
    def convert_to_for_loop(cursor: CursorDefinition, loop_body: str = "") -> str:
        """Convert CURSOR loop to PL/pgSQL FOR loop.

        Best for iterating over query results without passing cursor out.
        """
        if not cursor.query:
            return ""

        # Determine loop variable name
        loop_var = cursor.loop_variable or "r"

        # Build FOR loop
        sql = f"FOR {loop_var} IN {cursor.query}\n"
        sql += "LOOP\n"

        if loop_body:
            # Indent the loop body
            indented_body = "\n".join(f"    {line}" for line in loop_body.split("\n"))
            sql += indented_body + "\n"
        else:
            sql += "    -- Process row\n"

        sql += "END LOOP;"

        return sql

    @staticmethod
    def convert_to_refcursor_function(cursor: CursorDefinition) -> str:
        """Convert CURSOR to REFCURSOR-based function.

        Best when cursor needs to be returned or passed between functions.
        """
        if not cursor.query:
            return ""

        cursor_name = cursor.cursor_name.lstrip("@")
        function_name = f"get_{cursor_name}"

        sql = (
            f"CREATE OR REPLACE FUNCTION {function_name}(p_cursor REFCURSOR DEFAULT NULL)\n"
            f"RETURNS TABLE (record RECORD) AS $$\n"
            f"DECLARE\n"
            f"    l_cursor REFCURSOR := p_cursor;\n"
            f"BEGIN\n"
            f"    OPEN l_cursor FOR {cursor.query};\n"
            f"    RETURN NEXT;\n"
            f"END;\n"
            f"$$ LANGUAGE plpgsql;"
        )

        return sql

    @staticmethod
    def apply_all(sql: str) -> ConversionResult:
        """Analyze and convert CURSOR operations.

        Returns:
            ConversionResult with converted SQL and metadata.
        """
        result = ConversionResult(sql=sql)

        if "CURSOR" not in sql.upper():
            return result

        # Parse cursor
        cursor = CursorHandler.parse_cursor(sql)
        if not cursor or not cursor.query:
            result.warnings.append("CURSOR found but could not parse query")
            result.conversion_type = "manual"
            return result

        # Extract loop body if present
        loop_body_match = CursorHandler._CURSOR_LOOP_BODY.search(sql)
        loop_body = loop_body_match.group(1).strip() if loop_body_match else ""

        # Choose conversion strategy
        if cursor.uses_refcursor:
            converted = CursorHandler.convert_to_refcursor_function(cursor)
            result.conversion_type = "refcursor_function"
            result.warnings.append("Converted to REFCURSOR-based function")
        elif cursor.has_fetch_status_check and loop_body:
            converted = CursorHandler.convert_to_for_loop(cursor, loop_body)
            result.conversion_type = "for_loop"
            result.warnings.append("Converted CURSOR loop to FOR loop")
        else:
            converted = CursorHandler.convert_to_for_loop(cursor)
            result.conversion_type = "for_loop"
            result.warnings.append("Converted CURSOR to FOR loop (basic pattern)")

        if converted:
            result.sql = converted
            result.success = True
        else:
            result.conversion_type = "manual"
            result.warnings.append("CURSOR conversion incomplete; manual review required")

        return result


class CursorWarnings:
    """Generate warnings for CURSOR usage patterns."""

    @staticmethod
    def analyze_cursor_usage(sql: str) -> List[str]:
        """Analyze CURSOR usage and generate warnings.

        Returns:
            List of warnings about CURSOR conversion.
        """
        warnings = []

        if "CURSOR" not in sql.upper():
            return warnings

        # Check for complex cursor operations
        if "DEALLOCATE" in sql.upper():
            warnings.append("DEALLOCATE statement has no direct equivalent in PostgreSQL; cleanup is automatic")

        # Check for UPDATE/DELETE with cursor
        if re.search(r"UPDATE|DELETE.*WHERE\s+CURRENT\s+OF", sql, re.IGNORECASE):
            warnings.append(
                "Cursor-based UPDATE/DELETE (WHERE CURRENT OF) requires manual refactoring; "
                "use parameterized queries instead"
            )

        # Check for nested cursors
        if sql.count("DECLARE") > 1:
            warnings.append("Multiple DECLARE statements detected; verify nested cursor handling")

        # Check for dynamic cursor queries
        if re.search(r"EXEC|sp_executesql", sql, re.IGNORECASE):
            warnings.append("CURSOR with dynamic SQL; ensure parameterization in PostgreSQL")

        return warnings
