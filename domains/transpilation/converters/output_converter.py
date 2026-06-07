"""
Module: domains/transpilation/converters/output_converter.py
Purpose: Convert T-SQL OUTPUT clause to PostgreSQL RETURNING clause.

T-SQL OUTPUT Pattern:
    INSERT INTO target (col1, col2)
    OUTPUT INSERTED.id, INSERTED.col1
    VALUES (val1, val2);

    UPDATE target SET col1 = val1
    OUTPUT DELETED.id, INSERTED.col1;

    DELETE FROM target WHERE condition
    OUTPUT DELETED.*;

PostgreSQL RETURNING Pattern:
    INSERT INTO target (col1, col2)
    VALUES (val1, val2)
    RETURNING id, col1;

    UPDATE target SET col1 = val1
    RETURNING old_id, new_col1;  -- Note: old values must be tracked separately

    DELETE FROM target WHERE condition
    RETURNING *;

Author: Claude Code (Haiku 4.5)
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List


@dataclass
class ConversionResult:
    """Result of OUTPUT to RETURNING conversion."""

    sql: str
    success: bool = False
    warnings: List[str] = field(default_factory=list)
    columns_returned: List[str] = field(default_factory=list)


class OutputConverter:
    """Converts T-SQL OUTPUT clause to PostgreSQL RETURNING."""

    # Regex patterns
    _OUTPUT_CLAUSE = re.compile(
        r"OUTPUT\s+(.+?)(?=;|$)",
        re.IGNORECASE | re.DOTALL,
    )

    _INSERTED_REF = re.compile(
        r"INSERTED\.(\w+)|INSERTED\.\*",
        re.IGNORECASE,
    )

    _DELETED_REF = re.compile(
        r"DELETED\.(\w+)|DELETED\.\*",
        re.IGNORECASE,
    )

    @staticmethod
    def extract_output_clause(sql: str) -> tuple[str, List[str]] | tuple[None, None]:
        """Extract OUTPUT clause and return column list.

        Returns:
            Tuple of (output_clause, column_list) or (None, None) if not found.
        """
        match = OutputConverter._OUTPUT_CLAUSE.search(sql)
        if not match:
            return None, None

        output_content = match.group(1).strip()

        # Parse column references
        columns = []

        # Handle INSERTED.*
        if "INSERTED.*" in output_content:
            columns.append("*")
            return output_content, columns

        # Handle DELETED.*
        if "DELETED.*" in output_content:
            columns.append("*")
            return output_content, columns

        # Parse individual column references
        inserted_matches = OutputConverter._INSERTED_REF.finditer(output_content)
        for match in inserted_matches:
            col = match.group(1) if match.group(1) else "*"
            if col not in columns:
                columns.append(col)

        deleted_matches = OutputConverter._DELETED_REF.finditer(output_content)
        for match in deleted_matches:
            col = match.group(1) if match.group(1) else "*"
            if col not in columns:
                columns.append(col)

        return output_content, columns if columns else None

    @staticmethod
    def normalize_column_references(output_clause: str) -> str:
        """Replace INSERTED./DELETED. prefixes with direct column names.

        In RETURNING, we refer to values directly:
        - INSERTED.col → col (new values)
        - DELETED.col → col (old values, may need OLD prefix)
        """
        normalized = output_clause

        # Replace INSERTED.col with col
        normalized = re.sub(
            r"INSERTED\.(\w+)",
            r"\1",
            normalized,
            flags=re.IGNORECASE,
        )

        # Replace DELETED.col with col (or could use OLD.col in some contexts)
        normalized = re.sub(
            r"DELETED\.(\w+)",
            r"\1",
            normalized,
            flags=re.IGNORECASE,
        )

        # Handle wildcards
        normalized = normalized.replace("INSERTED.*", "*").replace("DELETED.*", "*")

        return normalized

    @staticmethod
    def convert_output_to_returning(sql: str) -> str:
        """Convert OUTPUT clause to RETURNING clause.

        Simple approach: Remove OUTPUT clause and add RETURNING with extracted columns.
        """
        output_clause, columns = OutputConverter.extract_output_clause(sql)

        if not output_clause:
            return sql

        # Normalize column references
        normalized_cols = OutputConverter.normalize_column_references(output_clause)

        # Remove OUTPUT clause
        converted = re.sub(
            r"OUTPUT\s+.+?(?=;|$)",
            "",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )

        # Add RETURNING clause before semicolon
        if converted.rstrip().endswith(";"):
            converted = converted.rstrip()[:-1]  # Remove trailing semicolon
            converted = f"{converted.strip()}\nRETURNING {normalized_cols};"
        else:
            converted = f"{converted.strip()}\nRETURNING {normalized_cols};"

        return converted

    @staticmethod
    def apply_all(sql: str) -> ConversionResult:
        """Convert OUTPUT to RETURNING.

        Returns:
            ConversionResult with converted SQL and metadata.
        """
        result = ConversionResult(sql=sql)

        if "OUTPUT" not in sql.upper():
            return result

        # Extract OUTPUT clause
        output_clause, columns = OutputConverter.extract_output_clause(sql)

        if not output_clause:
            result.warnings.append("OUTPUT clause found but could not parse column list")
            result.conversion_type = "manual"
            return result

        # Convert
        try:
            converted = OutputConverter.convert_output_to_returning(sql)
            result.sql = converted
            result.success = True
            result.columns_returned = columns or []
            result.warnings.append(f"Converted OUTPUT to RETURNING ({len(columns or [])} columns)")
        except Exception as e:
            result.warnings.append(f"Conversion failed: {e}")
            result.conversion_type = "manual"

        return result


class OutputWarnings:
    """Generate warnings for OUTPUT usage patterns."""

    @staticmethod
    def analyze_output_usage(sql: str) -> List[str]:
        """Analyze OUTPUT usage and generate relevant warnings.

        Returns:
            List of warnings about OUTPUT conversion.
        """
        warnings = []

        if "OUTPUT" not in sql.upper():
            return warnings

        # Check for DELETED references (require special handling)
        if "DELETED" in sql.upper():
            warnings.append("OUTPUT references DELETED values; ensure old values are tracked separately")

        # Check for complex expressions in OUTPUT
        if re.search(r"OUTPUT\s+.+[+\-*/()]", sql, re.IGNORECASE):
            warnings.append("OUTPUT clause contains expressions; verify RETURNING expression compatibility")

        # Check for OUTPUT INTO (separate table)
        if re.search(r"OUTPUT\s+.+\s+INTO\s+", sql, re.IGNORECASE):
            warnings.append(
                "OUTPUT ... INTO not supported in PostgreSQL; "
                "capture RETURNING results in application code or CTE"
            )

        return warnings
