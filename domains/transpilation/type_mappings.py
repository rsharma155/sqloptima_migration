"""
Module: type_mappings.py
Purpose: SQL Server to PostgreSQL data type mapping definitions
Author: Migration Platform Team
Created: 2026-05-22
Domain: Transpilation
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from domains.transpilation.transformation_rule import DataTypeMappingRule

# Comprehensive SQL Server → PostgreSQL data type mappings
# Based on industry-standard mapping tables and PostgreSQL documentation

DATA_TYPE_MAPPINGS: list[DataTypeMappingRule] = [
    # Exact Numeric
    DataTypeMappingRule(name="int_to_integer", category="datatype", source_type="INT", target_type="INTEGER"),
    DataTypeMappingRule(name="bigint_to_bigint", category="datatype", source_type="BIGINT", target_type="BIGINT"),
    DataTypeMappingRule(name="smallint_to_smallint", category="datatype", source_type="SMALLINT", target_type="SMALLINT"),
    DataTypeMappingRule(name="tinyint_to_smallint", category="datatype", source_type="TINYINT", target_type="SMALLINT",
                        description="PostgreSQL lacks TINYINT; mapped to SMALLINT"),
    DataTypeMappingRule(name="bit_to_boolean", category="datatype", source_type="BIT", target_type="BOOLEAN"),
    DataTypeMappingRule(name="decimal_to_numeric", category="datatype", source_type="DECIMAL", target_type="NUMERIC"),
    DataTypeMappingRule(name="numeric_to_numeric", category="datatype", source_type="NUMERIC", target_type="NUMERIC"),
    DataTypeMappingRule(name="money_to_numeric_19_4", category="datatype", source_type="MONEY", target_type="NUMERIC",
                        target_precision=19, target_scale=4),
    DataTypeMappingRule(name="smallmoney_to_numeric_10_4", category="datatype", source_type="SMALLMONEY", target_type="NUMERIC",
                        target_precision=10, target_scale=4),

    # Approximate Numeric
    DataTypeMappingRule(name="float_to_double", category="datatype", source_type="FLOAT", target_type="DOUBLE PRECISION"),
    DataTypeMappingRule(name="real_to_real", category="datatype", source_type="REAL", target_type="REAL"),

    # Date and Time
    DataTypeMappingRule(name="datetime_to_timestamp", category="datatype", source_type="DATETIME", target_type="TIMESTAMP"),
    DataTypeMappingRule(name="datetime2_to_timestamp", category="datatype", source_type="DATETIME2", target_type="TIMESTAMP"),
    DataTypeMappingRule(name="smalldatetime_to_timestamp", category="datatype", source_type="SMALLDATETIME", target_type="TIMESTAMP"),
    DataTypeMappingRule(name="date_to_date", category="datatype", source_type="DATE", target_type="DATE"),
    DataTypeMappingRule(name="time_to_time", category="datatype", source_type="TIME", target_type="TIME"),
    DataTypeMappingRule(name="datetimeoffset_to_timestamptz", category="datatype", source_type="DATETIMEOFFSET",
                        target_type="TIMESTAMPTZ"),

    # Character Strings
    DataTypeMappingRule(name="char_to_char", category="datatype", source_type="CHAR", target_type="CHAR"),
    DataTypeMappingRule(name="varchar_to_varchar", category="datatype", source_type="VARCHAR", target_type="VARCHAR"),
    DataTypeMappingRule(name="nvarchar_to_varchar", category="datatype", source_type="NVARCHAR", target_type="VARCHAR",
                        description="PostgreSQL UTF-8 native; NVARCHAR maps to VARCHAR"),
    DataTypeMappingRule(name="nchar_to_char", category="datatype", source_type="NCHAR", target_type="CHAR",
                        description="PostgreSQL UTF-8 native; NCHAR maps to CHAR"),
    DataTypeMappingRule(name="text_to_text", category="datatype", source_type="TEXT", target_type="TEXT"),
    DataTypeMappingRule(name="ntext_to_text", category="datatype", source_type="NTEXT", target_type="TEXT"),

    # Binary
    DataTypeMappingRule(name="binary_to_bytea", category="datatype", source_type="BINARY", target_type="BYTEA"),
    DataTypeMappingRule(name="varbinary_to_bytea", category="datatype", source_type="VARBINARY", target_type="BYTEA"),
    DataTypeMappingRule(name="image_to_bytea", category="datatype", source_type="IMAGE", target_type="BYTEA"),

    # Special Types
    DataTypeMappingRule(name="uniqueidentifier_to_uuid", category="datatype", source_type="UNIQUEIDENTIFIER",
                        target_type="UUID"),
    DataTypeMappingRule(name="xml_to_xml", category="datatype", source_type="XML", target_type="XML"),
    DataTypeMappingRule(name="json_to_jsonb", category="datatype", source_type="JSON", target_type="JSONB",
                        description="PostgreSQL JSONB is more performant"),
    DataTypeMappingRule(name="sql_variant_to_jsonb", category="datatype", source_type="SQL_VARIANT", target_type="JSONB",
                        description="SQL_VARIANT has no direct PG equivalent; use JSONB"),
    DataTypeMappingRule(name="rowversion_to_bytea", category="datatype", source_type="ROWVERSION", target_type="BYTEA"),
    DataTypeMappingRule(name="timestamp_type_to_bytea", category="datatype", source_type="TIMESTAMP", target_type="BYTEA",
                        description="SQL Server TIMESTAMP is a binary incrementing value, not a date/time"),

    # Spatial (Require PostGIS extension)
    DataTypeMappingRule(name="geography_to_postgis", category="datatype", source_type="GEOGRAPHY", target_type="GEOGRAPHY",
                        properties={"extension": "postgis"}),
    DataTypeMappingRule(name="geometry_to_postgis", category="datatype", source_type="GEOMETRY", target_type="GEOMETRY",
                        properties={"extension": "postgis"}),

    # Hierarchy (Requires ltree extension)
    DataTypeMappingRule(name="hierarchyid_to_ltree", category="datatype", source_type="HIERARCHYID", target_type="LTREE",
                        properties={"extension": "ltree"}),
]


def get_type_mapping_rules() -> list[DataTypeMappingRule]:
    """Return all data type mapping rules."""
    return DATA_TYPE_MAPPINGS.copy()


def get_type_mapping(source_type: str) -> DataTypeMappingRule:
    """Find the mapping rule for a given source type."""
    for rule in DATA_TYPE_MAPPINGS:
        if rule.source_type.upper() == source_type.upper():
            return rule
    # Fallback: pass through
    return DataTypeMappingRule(
        name=f"{source_type.lower()}_passthrough",
        category="datatype",
        source_type=source_type,
        target_type=source_type.upper(),
    )
