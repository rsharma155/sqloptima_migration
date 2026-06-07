"""
Module: identifier_converter.py
Purpose: Handles identifier case conversion, quoting, and naming conventions
         for SQL Server to PostgreSQL migration.
Domain: Transpilation
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

import re
from enum import StrEnum
from typing import Optional


class CaseTreatment(StrEnum):
    LOWERCASE = "lowercase"
    KEEP_CASE = "keep_case"
    SNAKE_CASE = "snake_case"


MAX_IDENTIFIER_LENGTH = 63


class IdentifierConverter:
    """Converts SQL Server identifiers to PostgreSQL conventions.

    Handles:
    - Lowercase conversion (PostgreSQL default)
    - CamelCase -> snake_case conversion
    - Double-quoting identifiers when case is preserved
    - Index column ASC/DESC handling
    - Warning on > 63 char identifiers
    """

    def __init__(
        self,
        treatment: CaseTreatment = CaseTreatment.LOWERCASE,
        always_quote: bool = False,
    ):
        self.treatment = treatment
        self.always_quote = always_quote

    def convert(self, identifier: str) -> str:
        """Convert identifier per the configured case treatment.

        Returns the identifier without quoting for LOWERCASE/SNAKE_CASE,
        and with quoting for KEEP_CASE.
        """
        converted = self._apply_case(identifier)

        if len(converted) > MAX_IDENTIFIER_LENGTH:
            import warnings as wrn
            wrn.warn(
                f"Identifier '{converted}' exceeds {MAX_IDENTIFIER_LENGTH} characters; "
                f"PostgreSQL will truncate it internally."
            )

        return converted

    def quote(self, identifier: str) -> str:
        """Quote an identifier with double quotes for PostgreSQL.

        Properly escapes embedded double quotes.
        """
        raw = self._apply_case(identifier)
        escaped = raw.replace('"', '""')
        return f'"{escaped}"'

    def convert_and_quote(self, identifier: str) -> str:
        """Convert case and quote. For KEEP_CASE, this is required.

        For LOWERCASE and SNAKE_CASE, quoting is optional (not returned here
        unless always_quote is True).
        """
        if self.treatment == CaseTreatment.KEEP_CASE or self.always_quote:
            return self.quote(identifier)
        return self.convert(identifier)

    def convert_index_column(self, index_col_expr: str) -> str:
        """Convert an index column expression that may include ASC/DESC.

        e.g., "col1 ASC" -> '"col1" ASC' or 'col1 ASC'
        """
        m = re.match(r'^(.*?)(?:\s+(ASC|DESC))?$', index_col_expr.strip(), re.IGNORECASE)
        if not m:
            return self.convert_and_quote(index_col_expr)

        col_name = m.group(1).strip()
        sort_order = m.group(2)
        converted_col = self.convert_and_quote(col_name)
        if sort_order:
            return f"{converted_col} {sort_order.upper()}"
        return converted_col

    def _apply_case(self, identifier: str) -> str:
        """Apply the configured case transformation."""
        if self.treatment == CaseTreatment.LOWERCASE:
            return identifier.lower()
        if self.treatment == CaseTreatment.SNAKE_CASE:
            return self._camel_to_snake(identifier)
        return identifier  # KEEP_CASE

    @staticmethod
    def _camel_to_snake(name: str) -> str:
        """Convert CamelCase to snake_case.

        e.g., 'FirstName' -> 'first_name', 'XMLParser' -> 'xml_parser'
        """
        if not name:
            return name

        result = name[0].lower()
        for i, ch in enumerate(name[1:], 1):
            if ch.isupper():
                prev = name[i - 1]
                # Insert underscore between lower->upper transitions
                if prev.islower() or prev.isdigit():
                    result += '_'
                # Handle consecutive uppercase followed by lowercase (XMLParser -> xml_parser)
                elif (i + 1 < len(name) and name[i + 1].islower()):
                    result += '_'
                result += ch.lower()
            elif ch.isdigit():
                result += ch
            else:
                result += ch

        # Collapse multiple underscores
        result = re.sub(r'_+', '_', result)
        # Strip leading/trailing underscores
        result = result.strip('_')
        return result.lower()

    @staticmethod
    def is_reserved_word(identifier: str) -> bool:
        """Check if identifier is a PostgreSQL reserved word that needs quoting."""
        RESERVED_WORDS = {
            "ALL", "ANALYSE", "ANALYZE", "AND", "ANY", "ARRAY", "AS", "ASC",
            "ASYMMETRIC", "AUTHORIZATION", "BETWEEN", "BINARY", "BOTH", "CASE",
            "CAST", "CHECK", "COLLATE", "COLUMN", "CONCURRENTLY", "CONSTRAINT",
            "CREATE", "CROSS", "CURRENT_CATALOG", "CURRENT_DATE", "CURRENT_ROLE",
            "CURRENT_SCHEMA", "CURRENT_TIME", "CURRENT_TIMESTAMP", "CURRENT_USER",
            "DEFAULT", "DEFERRABLE", "DESC", "DISTINCT", "DO", "ELSE", "END",
            "EXCEPT", "EXISTS", "EXTRACT", "FALSE", "FETCH", "FOR", "FOREIGN",
            "FREEZE", "FROM", "FULL", "GRANT", "GROUP", "HAVING", "ILIKE",
            "IN", "INITIALLY", "INNER", "INTERSECT", "INTO", "IS", "ISNULL",
            "JOIN", "LATERAL", "LEADING", "LEFT", "LIKE", "LIMIT", "LOCALTIME",
            "LOCALTIMESTAMP", "NATURAL", "NEW", "NOT", "NOTNULL", "NULL",
            "OFF", "OFFSET", "OLD", "ON", "ONLY", "OR", "ORDER", "OUTER",
            "OVER", "OVERLAPS", "PLACING", "PRIMARY", "REFERENCES", "RETURNING",
            "RIGHT", "ROW", "ROWS", "SELECT", "SESSION_USER", "SIMILAR",
            "SOME", "SYMMETRIC", "TABLE", "TABLESAMPLE", "THEN", "TO", "TRAILING",
            "TRUE", "UNION", "UNIQUE", "USER", "USING", "VARIADIC", "VERBOSE",
            "WHEN", "WHERE", "WINDOW", "WITH", "ZONE",
        }
        return identifier.upper() in RESERVED_WORDS
