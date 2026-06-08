"""
Module: models.py
Purpose: Data models, enums, and dataclasses for the dynamic SQL converter
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class FragmentType(StrEnum):
    LITERAL = "literal"
    VARIABLE = "variable"
    EXPRESSION = "expression"


@dataclass(frozen=True)
class SqlFragment:
    ftype: FragmentType
    value: str
    original_var: str | None = None


@dataclass
class DynamicSqlStatement:
    fragments: list[SqlFragment] = field(default_factory=list)
    normalized_sql: str = ""
    uses_sp_executesql: bool = False
    params: dict[str, str] = field(default_factory=dict)


@dataclass
class ConditionalPredicate:
    variable: str
    condition: str
    sql_fragment: str
    negated: bool = False


class IrNodeType(StrEnum):
    PROGRAM = "program"
    STATEMENT_LIST = "statement_list"
    CREATE_FUNCTION = "create_function"
    SELECT = "select"
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"
    COLUMN_REF = "column_ref"
    TABLE_REF = "table_ref"
    FUNCTION_CALL = "function_call"
    PREDICATE = "predicate"
    WHERE = "where"
    JOIN = "join"
    ORDER_BY = "order_by"
    PARAMETER = "parameter"
    LITERAL = "literal"
    BLOCK = "block"
    DECLARE = "declare"
    SET = "set"
    IF = "if"
    RETURN = "return"
    RETURN_QUERY = "return_query"
    ASSIGNMENT = "assignment"
    EXEC = "exec"
    DYNAMIC_SQL = "dynamic_sql"
    BINARY_OP = "binary_op"
    CASE = "case"
    LIMIT = "limit"
    TEMP_TABLE = "temp_table"


@dataclass
class IrNode:
    node_type: IrNodeType
    value: Any = None
    children: list[IrNode] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)
    original_sql: str | None = None


@dataclass
class FunctionParameter:
    name: str
    data_type: str
    default_value: str | None = None


class FunctionKind(StrEnum):
    FUNCTION = "function"
    SCALAR = "scalar"
    TABLE = "table"
    PROCEDURE = "procedure"
    TRIGGER = "trigger"


@dataclass
class ProcedureNode:
    schema_name: str
    name: str
    parameters: list[FunctionParameter] = field(default_factory=list)
    body: list[IrNode] = field(default_factory=list)
    kind: FunctionKind = FunctionKind.PROCEDURE
    returns_table: bool = False
    return_columns: list[dict[str, str]] = field(default_factory=list)


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ConversionWarning:
    severity: Severity
    code: str
    message: str
    original_sql: str | None = None


@dataclass
class ConversionResult:
    success: bool
    procedure_name: str = ""
    source_sql: str = ""
    target_sql: str = ""
    normalized_sql: str = ""
    warnings: list[ConversionWarning] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
