"""
Module: type_enhancements.py
Purpose: Enhanced type handling for SQL Server to PostgreSQL type conversion.
         Handles special cases: sysname, sql_variant, geometry/geography,
         binary length constraints, numeric-to-int optimization.
Domain: Transpilation
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

import re
from typing import Optional

from pydantic import BaseModel


class TypeConversionResult(BaseModel):
    pg_type: str
    requires_postgis: bool = False
    check_constraints: list[str] = []
    warnings: list[str] = []
    requires_extension: Optional[str] = None


NUMERIC_PRECISION_TO_INT: dict[int, str] = {
    4: "SMALLINT",
    5: "SMALLINT",
    6: "SMALLINT",
    7: "SMALLINT",
    8: "SMALLINT",
    9: "INTEGER",
    10: "INTEGER",
    11: "INTEGER",
    12: "INTEGER",
    13: "INTEGER",
    14: "INTEGER",
    15: "INTEGER",
    16: "INTEGER",
    17: "INTEGER",
    18: "BIGINT",
}


class EnhancedTypeConverter:
    """Handles special type conversion cases beyond simple type mapping.

    Based on patterns from sqlserver2pgsql reference implementation,
    adapted for Python/IR architecture.
    """

    # Basic type mapping from the reference Perl script
    BASE_TYPES: dict[str, str] = {
        "INT": "INTEGER",
        "BIGINT": "BIGINT",
        "SMALLINT": "SMALLINT",
        "TINYINT": "SMALLINT",
        "BIT": "BOOLEAN",
        "DECIMAL": "NUMERIC",
        "MONEY": "NUMERIC",
        "SMALLMONEY": "NUMERIC(6,4)",
        "FLOAT": "DOUBLE PRECISION",
        "REAL": "REAL",
        "DATE": "DATE",
        "DATETIME": "TIMESTAMP",
        "DATETIME2": "TIMESTAMP",
        "SMALLDATETIME": "TIMESTAMP",
        "TIME": "TIME",
        "DATETIMEOFFSET": "TIMESTAMPTZ",
        "CHAR": "CHAR",
        "VARCHAR": "VARCHAR",
        "NCHAR": "CHAR",
        "NVARCHAR": "VARCHAR",
        "TEXT": "TEXT",
        "NTEXT": "TEXT",
        "BINARY": "BYTEA",
        "VARBINARY": "BYTEA",
        "IMAGE": "BYTEA",
        "TIMESTAMP": "BYTEA",
        "ROWVERSION": "BYTEA",
        "UNIQUEIDENTIFIER": "UUID",
        "XML": "XML",
        "JSON": "JSONB",
        "SQL_VARIANT": "JSONB",
    }

    # Types that should not carry qualifiers (precision/scale/length)
    UNQUALIFIED_TYPES: set[str] = {"BYTEA", "TIMESTAMPTZ", "UUID", "JSONB", "XML", "BOOLEAN", "TEXT"}

    def __init__(self, optimize_numeric: bool = False):
        self.optimize_numeric = optimize_numeric
        self.requires_postgis = False

    def convert_type(
        self,
        type_name: str,
        qualifier: Optional[str] = None,
        column_name: Optional[str] = None,
        table_name: Optional[str] = None,
        schema_name: Optional[str] = None,
    ) -> TypeConversionResult:
        """Convert a T-SQL type to PostgreSQL, handling special cases.

        Handles:
        - sysname -> varchar(128)
        - sql_variant -> text (with warning)
        - geometry/geography -> PostGIS types (with extension requirement)
        - numeric(N,0) -> smallint/integer/bigint (when optimize_numeric=True)
        - binary/varbinary -> BYTEA with CHECK constraint for length
        - Named type patterns (schema.type) -> array type for TVPs
        """
        upper_type = type_name.upper().strip()
        result = TypeConversionResult(pg_type="TEXT")

        # Special type: sysname
        if upper_type == "SYSNAME":
            result.pg_type = "VARCHAR(128)"
            return result

        # Spatial types: geometry/geography -> PostGIS
        if upper_type in ("GEOGRAPHY", "GEOMETRY"):
            self.requires_postgis = True
            result.pg_type = upper_type.lower()
            result.requires_postgis = True
            result.requires_extension = "postgis"
            result.warnings.append(
                f"PostGIS extension required for {upper_type} type"
            )
            return result

        # SQL_VARIANT -> text (no direct equivalent in PostgreSQL)
        if upper_type == "SQL_VARIANT":
            result.pg_type = "TEXT"
            result.warnings.append(
                "SQL_VARIANT has no direct PostgreSQL equivalent; converted to TEXT"
            )
            return result

        # HierarchyID -> ltree (requires extension)
        if upper_type == "HIERARCHYID":
            result.pg_type = "LTREE"
            result.requires_extension = "ltree"
            result.warnings.append(
                "ltree extension required for HIERARCHYID type"
            )
            return result

        # Numeric special handling
        if upper_type == "NUMERIC":
            return self._convert_numeric(qualifier)

        # Binary types with length -> CHECK constraint
        if upper_type in ("BINARY", "VARBINARY") and qualifier:
            result.pg_type = "BYTEA"
            if column_name and table_name:
                constraint = (
                    f"CHECK (octet_length({column_name}) <= {qualifier})"
                )
                result.check_constraints.append(constraint)
            return result

        # Named type pattern: schema.TypeName -> check if TVP
        if re.match(r'^(\w+)\.(\w+)$', upper_type):
            result.pg_type = self._convert_named_type(upper_type)
            return result

        # Base types
        if upper_type in self.BASE_TYPES:
            pg_base = self.BASE_TYPES[upper_type]

            # Check if qualifier should be dropped
            if pg_base.upper() in self.UNQUALIFIED_TYPES:
                result.pg_type = pg_base
                # For BYTEA from TIMESTAMP, add warning
                if upper_type == "TIMESTAMP":
                    result.warnings.append(
                        "SQL Server TIMESTAMP is a binary incrementing value, "
                        "not a date/time type"
                    )
                return result

            # Apply qualifier
            if qualifier:
                result.pg_type = f"{pg_base}({qualifier})"
            else:
                result.pg_type = pg_base
            return result

        # Fallback: pass through as-is
        result.pg_type = upper_type
        return result

    def _convert_numeric(self, qualifier: Optional[str]) -> TypeConversionResult:
        """Handle NUMERIC type with optional precision/scale."""
        result = TypeConversionResult(pg_type="NUMERIC")

        if not qualifier:
            result.pg_type = "NUMERIC"
            return result

        m = re.match(r'^(\d+),\s*(\d+)$', qualifier)
        if not m:
            result.pg_type = f"NUMERIC({qualifier})"
            return result

        precision = int(m.group(1))
        scale = int(m.group(2))

        if scale == 0 and self.optimize_numeric:
            # Convert numeric(N,0) to int types for performance
            if precision <= 4:
                result.pg_type = "SMALLINT"
            elif precision <= 9:
                result.pg_type = "INTEGER"
            elif precision <= 18:
                result.pg_type = "BIGINT"
            else:
                result.pg_type = f"NUMERIC({qualifier})"
        else:
            result.pg_type = f"NUMERIC({qualifier})"

        return result

    def _convert_named_type(self, named_type: str) -> str:
        """Convert a schema-qualified type name.

        If it's a known TVP type, append [] to make it an array.
        """
        # TVP types end in common suffixes
        tvp_suffixes = ("_TT", "_TVP", "_TABLE_TYPE", "_LIST", "TABLE_TYPE")
        parts = named_type.split(".")
        local_name = parts[1].upper() if len(parts) > 1 else parts[0].upper()

        if any(local_name.endswith(suffix.upper()) for suffix in tvp_suffixes):
            return f"{named_type}[]"
        return named_type

    @staticmethod
    def needs_cast(pg_type: str) -> bool:
        """Check if this PostgreSQL type needs a cast for data migration.

        Types requiring CAST for ETL tools: uuid, date, timestamptz, xml
        """
        base = re.split(r'[\(\s]', pg_type.upper())[0]
        return base in ("UUID", "DATE", "TIMESTAMPTZ", "XML")
