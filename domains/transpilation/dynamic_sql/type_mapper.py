"""
Module: type_mapper.py
Purpose: Maps SQL Server data types and built-in functions to PostgreSQL equivalents.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import re
from typing import Any

from domains.transpilation.dynamic_sql.models import ConversionWarning, Severity

TYPE_MAPPINGS: dict[str, str] = {
    "BIGINT": "BIGINT",
    "BINARY": "BYTEA",
    "BIT": "BOOLEAN",
    "CHAR": "CHAR",
    "DATE": "DATE",
    "DATETIME": "TIMESTAMP",
    "DATETIME2": "TIMESTAMP",
    "DATETIMEOFFSET": "TIMESTAMPTZ",
    "DECIMAL": "NUMERIC",
    "FLOAT": "DOUBLE PRECISION",
    "IMAGE": "BYTEA",
    "INT": "INTEGER",
    "MONEY": "NUMERIC",
    "NCHAR": "CHAR",
    "NTEXT": "TEXT",
    "NUMERIC": "NUMERIC",
    "NVARCHAR": "VARCHAR",
    "NVARCHAR(MAX)": "TEXT",
    "REAL": "REAL",
    "SMALLDATETIME": "TIMESTAMP",
    "SMALLINT": "SMALLINT",
    "SMALLMONEY": "NUMERIC",
    "SQL_VARIANT": "JSONB",
    "TEXT": "TEXT",
    "TIME": "TIME",
    "TIMESTAMP": "BYTEA",
    "TINYINT": "SMALLINT",
    "UNIQUEIDENTIFIER": "UUID",
    "VARBINARY": "BYTEA",
    "VARBINARY(MAX)": "BYTEA",
    "VARCHAR": "VARCHAR",
    "VARCHAR(MAX)": "TEXT",
    "XML": "XML",
}

FUNCTION_MAPPINGS: dict[str, str] = {
    "ISNULL": "COALESCE",
    "GETDATE": "CURRENT_TIMESTAMP",
    "GETUTCDATE": "CURRENT_TIMESTAMP AT TIME ZONE 'UTC'",
    "SYSDATETIME": "CURRENT_TIMESTAMP",
    "SYSUTCDATETIME": "CURRENT_TIMESTAMP AT TIME ZONE 'UTC'",
    "NEWID": "gen_random_uuid()",
    "NEWSEQUENTIALID": "gen_random_uuid()",
    "LEN": "LENGTH",
    "DATALENGTH": "OCTET_LENGTH",
    "CHARINDEX": "POSITION",
    "PATINDEX": "POSITION",
    "SUBSTRING": "SUBSTRING",
    "LEFT": "LEFT",
    "RIGHT": "RIGHT",
    "REPLACE": "REPLACE",
    "REVERSE": "REVERSE",
    "UPPER": "UPPER",
    "LOWER": "LOWER",
    "LTRIM": "LTRIM",
    "RTRIM": "RTRIM",
    "TRIM": "TRIM",
    "SPACE": "REPEAT",
    "REPLICATE": "REPEAT",
    "STUFF": "OVERLAY",
    "DATEDIFF": "EXTRACT",
    "DATEADD": "INTERVAL",
    "DATEPART": "EXTRACT",
    "YEAR": "EXTRACT(YEAR FROM",
    "MONTH": "EXTRACT(MONTH FROM",
    "DAY": "EXTRACT(DAY FROM",
    "GETANSI NULL": "NULLIF",
    "COALESCE": "COALESCE",
    "NULLIF": "NULLIF",
    "IIF": "CASE WHEN",
    "CHOOSE": "CASE",
    "CONVERT": "CAST",
    "CAST": "CAST",
    "TRY_CAST": "CAST",
    "TRY_CONVERT": "CAST",
    "ABS": "ABS",
    "CEILING": "CEIL",
    "FLOOR": "FLOOR",
    "ROUND": "ROUND",
    "POWER": "POWER",
    "SQUARE": "POWER",
    "SQRT": "SQRT",
    "RAND": "RANDOM",
    "COUNT": "COUNT",
    "SUM": "SUM",
    "AVG": "AVG",
    "MIN": "MIN",
    "MAX": "MAX",
    "STRING_AGG": "STRING_AGG",
    "ROW_NUMBER": "ROW_NUMBER",
    "RANK": "RANK",
    "DENSE_RANK": "DENSE_RANK",
    "NTILE": "NTILE",
    "LEAD": "LEAD",
    "LAG": "LAG",
    "FIRST_VALUE": "FIRST_VALUE",
    "LAST_VALUE": "LAST_VALUE",
    "OBJECT_NAME": "pg_catalog.obj_description",
    "HASHBYTES": "pg_catalog.digest",
    "CHECKSUM": "hashint4",
    "BINARY_CHECKSUM": "hashint4",
}

KEYWORD_MAPPINGS: dict[str, str] = {
    "TOP": "LIMIT",
    "WITH (NOLOCK)": "",
    "WITH (READUNCOMMITTED)": "",
    "WITH (READCOMMITTED)": "",
    "WITH (REPEATABLEREAD)": "",
    "WITH (SERIALIZABLE)": "",
    "WITH (UPDLOCK)": "",
    "WITH (TABLOCK)": "",
    "WITH (TABLOCKX)": "",
    "WITH (NOWAIT)": "",
    "WITH (ROWLOCK)": "",
    "WITH (PAGLOCK)": "",
    "AS": "AS",
    "OUTPUT": "RETURNING",
    "IDENTITY": "SERIAL",
    "PRINT": "RAISE NOTICE",
}


class TypeMapper:
    """Maps SQL Server types and functions to PostgreSQL equivalents."""

    def __init__(self):
        self.warnings: list[ConversionWarning] = []

    def map_data_type(self, tsql_type: str) -> str:
        base = tsql_type.strip().upper()
        base = re.sub(r"\s+", " ", base)

        if base in TYPE_MAPPINGS:
            return TYPE_MAPPINGS[base]

        for tsql, pg in sorted(TYPE_MAPPINGS.items(), key=lambda x: -len(x[0])):
            if base.startswith(tsql):
                return base.replace(tsql, pg, 1)

        return tsql_type

    def map_function(self, func_name: str) -> str:
        upper = func_name.strip().upper()
        if upper in FUNCTION_MAPPINGS:
            return FUNCTION_MAPPINGS[upper]
        self.warnings.append(
            ConversionWarning(
                severity=Severity.LOW,
                code="UNMAPPED_FUNCTION",
                message=f"Function '{func_name}' has no PostgreSQL mapping",
            )
        )
        return func_name

    def replace_sql_keywords(self, sql: str) -> str:
        result = sql
        for tsql_kw, pg_kw in KEYWORD_MAPPINGS.items():
            pattern = re.compile(r"\b" + re.escape(tsql_kw) + r"\b", re.IGNORECASE)
            result = pattern.sub(pg_kw, result)
        return result

    def get_warnings(self) -> list[ConversionWarning]:
        return self.warnings
