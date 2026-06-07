"""
Module: domains/transpilation/converters/merge_converter.py
Purpose: Convert T-SQL MERGE statements to PostgreSQL INSERT ... ON CONFLICT DO UPDATE.

T-SQL MERGE Pattern:
    MERGE INTO target_table AS t
    USING source_table AS s
    ON t.key = s.key
    WHEN MATCHED THEN UPDATE SET t.col1 = s.col1, ...
    WHEN NOT MATCHED THEN INSERT (...) VALUES (...)
    WHEN NOT MATCHED BY SOURCE THEN DELETE;

PostgreSQL INSERT ... ON CONFLICT Pattern:
    INSERT INTO target_table (col1, col2, ...)
    SELECT col1, col2, ... FROM source_table
    ON CONFLICT (key_col) DO UPDATE SET col1 = EXCLUDED.col1, ...;

For complex MERGE with DELETE: use CTE-based approach.

Author: Claude Code (Haiku 4.5)
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class MergeStatement:
    """Parsed MERGE statement components."""

    target_table: str = ""
    target_alias: str = ""
    source_table: str = ""
    source_alias: str = ""
    join_condition: str = ""
    matched_updates: List[Tuple[str, str]] = field(default_factory=list)  # (col, value) pairs
    not_matched_inserts: List[str] = field(default_factory=list)  # Column list
    not_matched_values: List[str] = field(default_factory=list)  # Value expressions
    not_matched_by_source_delete: bool = False

    @property
    def is_complex(self) -> bool:
        """True if MERGE has DELETE clause (requires CTE approach)."""
        return self.not_matched_by_source_delete


@dataclass
class ConversionResult:
    """Result of MERGE conversion."""

    sql: str
    success: bool = False
    warnings: List[str] = field(default_factory=list)
    conversion_type: str = ""  # "insert_on_conflict" | "cte_upsert" | "manual"


class MergeConverter:
    """Converts T-SQL MERGE to PostgreSQL INSERT ... ON CONFLICT."""

    # Regex patterns for MERGE parsing
    _MERGE_START = re.compile(
        r"MERGE\s+INTO\s+([^\s]+)(?:\s+(?:AS\s+)?([^\s]+))?\s+USING\s+([^\s]+)(?:\s+(?:AS\s+)?([^\s]+))?",
        re.IGNORECASE,
    )

    _JOIN_CONDITION = re.compile(
        r"ON\s+(.+?)(?=WHEN|$)",
        re.IGNORECASE | re.DOTALL,
    )

    _MATCHED_UPDATE = re.compile(
        r"WHEN\s+MATCHED(?:\s+AND.+?)?\s+THEN\s+UPDATE\s+SET\s+(.+?)(?=WHEN|$)",
        re.IGNORECASE | re.DOTALL,
    )

    _NOT_MATCHED_INSERT = re.compile(
        r"WHEN\s+NOT\s+MATCHED(?:\s+BY\s+TARGET)?(?:\s+AND.+?)?\s+THEN\s+INSERT\s+\(([^)]+)\)\s+VALUES\s+\(([^)]+)\)",
        re.IGNORECASE | re.DOTALL,
    )

    _NOT_MATCHED_BY_SOURCE = re.compile(
        r"WHEN\s+NOT\s+MATCHED\s+BY\s+SOURCE\s+THEN\s+DELETE",
        re.IGNORECASE,
    )

    @staticmethod
    def parse_merge(sql: str) -> Optional[MergeStatement]:
        """Parse a MERGE statement into components.

        Returns:
            MergeStatement with extracted components, or None if parsing fails.
        """
        stmt = MergeStatement()

        # Parse MERGE INTO ... USING ...
        merge_match = MergeConverter._MERGE_START.search(sql)
        if not merge_match:
            return None

        stmt.target_table = merge_match.group(1).strip()
        stmt.target_alias = merge_match.group(2).strip() if merge_match.group(2) else stmt.target_table
        stmt.source_table = merge_match.group(3).strip()
        stmt.source_alias = merge_match.group(4).strip() if merge_match.group(4) else stmt.source_table

        # Parse ON condition
        join_match = MergeConverter._JOIN_CONDITION.search(sql)
        if join_match:
            stmt.join_condition = join_match.group(1).strip()

        # Parse WHEN MATCHED THEN UPDATE
        matched_match = MergeConverter._MATCHED_UPDATE.search(sql)
        if matched_match:
            update_clause = matched_match.group(1).strip()
            # Remove trailing WHEN, IF, etc.
            update_clause = re.sub(r'\s+(WHEN|IF|$).*', '', update_clause, flags=re.IGNORECASE | re.DOTALL)
            update_clause = update_clause.strip()
            # Split by comma outside parentheses
            pairs = MergeConverter._split_set_pairs(update_clause)
            stmt.matched_updates = pairs

        # Parse WHEN NOT MATCHED THEN INSERT
        insert_match = MergeConverter._NOT_MATCHED_INSERT.search(sql)
        if insert_match:
            cols_str = insert_match.group(1).strip()
            vals_str = insert_match.group(2).strip()
            # Split columns and values, respecting parentheses
            stmt.not_matched_inserts = [c.strip() for c in cols_str.split(",")]
            # More careful splitting of values to handle function calls
            values = []
            current_val = ""
            paren_depth = 0
            for char in vals_str:
                if char == "(":
                    paren_depth += 1
                elif char == ")":
                    paren_depth -= 1
                elif char == "," and paren_depth == 0:
                    values.append(current_val.strip())
                    current_val = ""
                    continue
                current_val += char
            if current_val.strip():
                values.append(current_val.strip())
            stmt.not_matched_values = values

        # Check for NOT MATCHED BY SOURCE DELETE
        if MergeConverter._NOT_MATCHED_BY_SOURCE.search(sql):
            stmt.not_matched_by_source_delete = True

        return stmt

    @staticmethod
    def _split_set_pairs(update_clause: str) -> List[Tuple[str, str]]:
        """Split 'col1=val1, col2=val2, ...' into [(col1, val1), (col2, val2), ...]."""
        pairs = []
        current_pair = ""
        paren_depth = 0

        for char in update_clause:
            if char == "(":
                paren_depth += 1
            elif char == ")":
                paren_depth -= 1
            elif char == "," and paren_depth == 0:
                if current_pair.strip():
                    parts = current_pair.split("=", 1)
                    if len(parts) == 2:
                        pairs.append((parts[0].strip(), parts[1].strip()))
                current_pair = ""
                continue

            current_pair += char

        if current_pair.strip():
            parts = current_pair.split("=", 1)
            if len(parts) == 2:
                pairs.append((parts[0].strip(), parts[1].strip()))

        return pairs

    @staticmethod
    def convert_to_insert_on_conflict(stmt: MergeStatement) -> str:
        """Convert a simple MERGE to INSERT ... ON CONFLICT DO UPDATE.

        Works for:
        - WHEN MATCHED THEN UPDATE (converts to ON CONFLICT DO UPDATE)
        - WHEN NOT MATCHED THEN INSERT (converts to INSERT)
        - Does NOT work for DELETE clause (use CTE approach instead)
        """
        if stmt.is_complex:
            return ""  # Use CTE approach instead

        # Extract key columns from join condition (e.g., "t.id = s.id" → "id")
        key_cols = MergeConverter._extract_key_columns(stmt.join_condition, stmt.target_alias)

        # Build INSERT clause
        all_cols = stmt.not_matched_inserts if stmt.not_matched_inserts else []
        if not all_cols:
            # Fallback: assume we're inserting the same columns we're updating
            all_cols = [col for col, _ in stmt.matched_updates]

        cols_list = ", ".join(all_cols)
        vals_list = ", ".join(stmt.not_matched_values) if stmt.not_matched_values else ""

        # If no explicit values, use SELECT from source
        if not vals_list:
            vals_clause = f"SELECT {cols_list} FROM {stmt.source_table}"
        else:
            vals_clause = f"VALUES ({vals_list})"

        # Build ON CONFLICT DO UPDATE clause
        update_parts = []
        for col, val in stmt.matched_updates:
            # Replace source alias references with EXCLUDED
            normalized_val = val.replace(f"{stmt.source_alias}.", "EXCLUDED.")
            update_parts.append(f"{col} = {normalized_val}")

        update_clause = ", ".join(update_parts)

        # Build final statement
        key_clause = ", ".join(key_cols) if key_cols else "id"  # Fallback to 'id'

        sql = (
            f"INSERT INTO {stmt.target_table} ({cols_list})\n"
            f"{vals_clause}\n"
            f"ON CONFLICT ({key_clause}) DO UPDATE SET {update_clause};"
        )

        return sql

    @staticmethod
    def convert_to_cte_upsert(stmt: MergeStatement) -> str:
        """Convert MERGE with DELETE to CTE-based UPSERT.

        Uses PostgreSQL CTE (Common Table Expression) to handle:
        - WHEN MATCHED THEN UPDATE
        - WHEN NOT MATCHED THEN INSERT
        - WHEN NOT MATCHED BY SOURCE THEN DELETE
        """
        key_cols = MergeConverter._extract_key_columns(stmt.join_condition, stmt.target_alias)

        if not key_cols:
            return ""  # Can't determine key columns

        # Build UPDATE CTE
        update_parts = []
        for col, val in stmt.matched_updates:
            normalized_val = val.replace(f"{stmt.source_alias}.", "s.")
            update_parts.append(f"{col} = {normalized_val}")

        update_clause = ", ".join(update_parts)
        key_condition = " AND ".join(
            [f"t.{k} = s.{k}" for k in key_cols]
        )

        sql_parts = [
            f"WITH updates AS (",
            f"  UPDATE {stmt.target_table} t",
            f"  SET {update_clause}",
            f"  FROM {stmt.source_table} s",
            f"  WHERE {key_condition}",
            f")",
        ]

        # Build INSERT for unmatched rows
        all_cols = stmt.not_matched_inserts or [col for col, _ in stmt.matched_updates]
        cols_list = ", ".join(all_cols)

        sql_parts.extend([
            f"INSERT INTO {stmt.target_table} ({cols_list})",
            f"SELECT {cols_list} FROM {stmt.source_table} s",
            f"WHERE NOT EXISTS (",
            f"  SELECT 1 FROM {stmt.target_table} t",
            f"  WHERE {key_condition}",
            f")",
        ])

        # Build DELETE for NOT MATCHED BY SOURCE
        if stmt.not_matched_by_source_delete:
            sql_parts.extend([
                f";",
                f"DELETE FROM {stmt.target_table} t",
                f"WHERE NOT EXISTS (",
                f"  SELECT 1 FROM {stmt.source_table} s",
                f"  WHERE {key_condition}",
                f")",
            ])

        return "\n".join(sql_parts) + ";"

    @staticmethod
    def _extract_key_columns(join_condition: str, target_alias: str) -> List[str]:
        """Extract key column names from join condition.

        Example: "t.id = s.id AND t.type = s.type" → ["id", "type"]
        """
        keys = []

        # Match patterns like "t.col = s.col" or "alias.col = ..."
        pattern = re.compile(
            rf"{re.escape(target_alias)}\.(\w+)\s*=",
            re.IGNORECASE,
        )

        for match in pattern.finditer(join_condition):
            col_name = match.group(1)
            if col_name not in keys:
                keys.append(col_name)

        return keys

    @staticmethod
    def apply_all(sql: str) -> ConversionResult:
        """Convert MERGE statement to PostgreSQL.

        Returns:
            ConversionResult with converted SQL and metadata.
        """
        result = ConversionResult(sql=sql)

        if "MERGE" not in sql.upper():
            return result

        # Parse the MERGE statement
        stmt = MergeConverter.parse_merge(sql)
        if not stmt:
            result.warnings.append("Could not parse MERGE statement structure")
            result.conversion_type = "manual"
            return result

        # Choose conversion strategy
        if stmt.is_complex:
            converted = MergeConverter.convert_to_cte_upsert(stmt)
            result.conversion_type = "cte_upsert"
            result.warnings.append("Using CTE-based UPSERT for MERGE with DELETE clause")
        else:
            converted = MergeConverter.convert_to_insert_on_conflict(stmt)
            result.conversion_type = "insert_on_conflict"

        if converted:
            result.sql = converted
            result.success = True
            result.warnings.append(f"MERGE converted to {result.conversion_type}")
        else:
            result.conversion_type = "manual"
            result.warnings.append("MERGE conversion failed; manual review required")

        return result
