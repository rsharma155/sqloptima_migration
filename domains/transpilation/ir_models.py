"""
Module: ir_models.py
Purpose: Normalized Intermediate Representation (IR) for AST nodes
Author: Migration Platform Team
Created: 2026-05-22
Domain: Transpilation
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class IrNodeType(StrEnum):
    # Statements
    CREATE_TABLE = "create_table"
    CREATE_VIEW = "create_view"
    CREATE_INDEX = "create_index"
    CREATE_PROCEDURE = "create_procedure"
    CREATE_FUNCTION = "create_function"
    CREATE_TRIGGER = "create_trigger"
    ALTER_TABLE = "alter_table"
    DROP = "drop"
    SELECT = "select"
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"
    MERGE = "merge"

    # Expressions
    COLUMN_REF = "column_ref"
    TABLE_REF = "table_ref"
    FUNCTION_CALL = "function_call"
    BINARY_OP = "binary_op"
    UNARY_OP = "unary_op"
    LITERAL = "literal"
    PARAMETER = "parameter"
    CAST = "cast"
    CASE = "case"
    SUBQUERY = "subquery"

    # Clauses
    WHERE = "where"
    JOIN = "join"
    ORDER_BY = "order_by"
    GROUP_BY = "group_by"
    HAVING = "having"
    LIMIT = "limit"
    TOP = "top"
    WINDOW = "window"

    # DDL Components
    COLUMN_DEF = "column_def"
    CONSTRAINT = "constraint"
    INDEX_COLUMN = "index_column"
    DATA_TYPE = "data_type"

    # Procedural
    BLOCK = "block"
    DECLARE = "declare"
    SET = "set"
    IF = "if"
    WHILE = "while"
    RETURN = "return"
    CALL = "call"
    EXEC = "exec"
    CURSOR = "cursor"
    TRY = "try"
    CATCH = "catch"
    RAISE = "raise"
    ASSIGNMENT = "assignment"

    # Root
    PROGRAM = "program"
    STATEMENT_LIST = "statement_list"


class IrNode(BaseModel):
    """A single node in the Intermediate Representation tree."""

    node_type: IrNodeType
    node_id: UUID = Field(default_factory=uuid4)
    value: Any = None
    children: list["IrNode"] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)
    source_location: str | None = None
    original_sql: str | None = None


class IrProgram(IrNode):
    """Root node for a complete IR tree."""

    node_type: IrNodeType = IrNodeType.PROGRAM
    statements: list[IrNode] = Field(default_factory=list)


class DataTypeNode(IrNode):
    """IR node for data type definitions."""

    node_type: IrNodeType = IrNodeType.DATA_TYPE
    type_name: str = ""
    precision: int | None = None
    scale: int | None = None
    max_length: int | None = None
    is_nullable: bool = True
    is_user_defined: bool = False
    schema_name: str | None = None


class ColumnDefNode(IrNode):
    """IR node for column definitions in DDL."""

    node_type: IrNodeType = IrNodeType.COLUMN_DEF
    column_name: str = ""
    data_type: DataTypeNode | None = None
    is_nullable: bool = True
    is_identity: bool = False
    is_primary_key: bool = False
    default_value: str | None = None
    is_computed: bool = False
    computed_expression: str | None = None
    collation: str | None = None
    constraints: list["ConstraintNode"] = Field(default_factory=list)


class ConstraintNode(IrNode):
    """IR node for constraints (PK, FK, CHECK, UNIQUE, DEFAULT)."""

    node_type: IrNodeType = IrNodeType.CONSTRAINT
    constraint_type: str = ""
    constraint_name: str | None = None
    columns: list[str] = Field(default_factory=list)
    referenced_table: str | None = None
    referenced_columns: list[str] = Field(default_factory=list)
    delete_rule: str | None = None
    update_rule: str | None = None
    check_expression: str | None = None
    is_disabled: bool = False
