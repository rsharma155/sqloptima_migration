"""
Module: ir_builder.py
Purpose: Builds Intermediate Representation (IR) tree from normalized SQL AST.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import re
from typing import Any

import sqlglot
from sqlglot import exp

from domains.transpilation.dynamic_sql.models import (
    ConversionWarning,
    IrNode,
    IrNodeType,
    ProcedureNode,
    Severity,
)


class IrBuilder:
    """Converts a normalized SQL string into an Intermediate Representation tree."""

    def __init__(self):
        self.warnings: list[ConversionWarning] = []
        self._current_procedure: ProcedureNode | None = None

    def build(self, normalized_sql: str) -> IrNode:
        """Parse normalized SQL and build IR tree."""
        try:
            parsed = sqlglot.parse(normalized_sql, read="tsql")
        except Exception as e:
            self.warnings.append(
                ConversionWarning(
                    severity=Severity.HIGH,
                    code="PARSE_FAILURE",
                    message=f"Failed to parse normalized SQL: {e}",
                    original_sql=normalized_sql,
                )
            )
            return IrNode(
                node_type=IrNodeType.BLOCK,
                value=normalized_sql,
                original_sql=normalized_sql,
            )

        statements: list[IrNode] = []
        for stmt in parsed:
            if stmt is None:
                continue
            node = self._convert_statement(stmt)
            if node is not None:
                statements.append(node)

        program = IrNode(
            node_type=IrNodeType.PROGRAM,
            children=statements,
        )
        return program

    def _convert_statement(self, stmt: exp.Expression) -> IrNode | None:
        stmt_type = type(stmt).__name__.upper()

        if isinstance(stmt, exp.Create):
            return self._convert_create(stmt)
        elif isinstance(stmt, exp.Select):
            return self._convert_select(stmt)
        elif isinstance(stmt, exp.Insert):
            return self._convert_insert(stmt)
        elif isinstance(stmt, exp.Update):
            return self._convert_update(stmt)
        elif isinstance(stmt, exp.Delete):
            return self._convert_delete(stmt)
        elif isinstance(stmt, exp.Set):
            return self._convert_set(stmt)
        elif isinstance(stmt, exp.If):
            return self._convert_if(stmt)
        elif isinstance(stmt, exp.Declare):
            return self._convert_declare(stmt)
        elif isinstance(stmt, exp.Return):
            return IrNode(node_type=IrNodeType.RETURN, original_sql=stmt.sql())
        elif isinstance(stmt, exp.Block):
            return self._convert_block(stmt)

        return IrNode(
            node_type=IrNodeType.BLOCK,
            value=stmt.sql(dialect="tsql") if hasattr(stmt, "sql") else str(stmt),
            original_sql=stmt.sql(dialect="tsql") if hasattr(stmt, "sql") else str(stmt),
        )

    def _convert_create(self, node: exp.Create) -> IrNode | None:
        kind = node.this
        if isinstance(kind, exp.UserDefinedFunction):
            return self._convert_user_defined_function(kind, node)
        return IrNode(
            node_type=IrNodeType.BLOCK,
            value=node.sql(dialect="tsql"),
            original_sql=node.sql(dialect="tsql"),
        )

    def _convert_user_defined_function(
        self, func_def: exp.UserDefinedFunction, create_node: exp.Create
    ) -> IrNode:
        name_parts: list[str] = []
        table_name = func_def.name
        if isinstance(table_name, exp.Table):
            name_parts = [
                p.name for p in table_name.parts if p.name
            ]
        elif isinstance(table_name, exp.Identifier):
            name_parts = [table_name.name]
        elif hasattr(table_name, "name"):
            name_parts = [table_name.name]

        node = IrNode(
            node_type=IrNodeType.CREATE_FUNCTION,
            properties={
                "schema": name_parts[0] if len(name_parts) > 1 else "dbo",
                "name": name_parts[-1] if name_parts else "unknown",
                "full_name": ".".join(name_parts) if name_parts else "unknown",
            },
            original_sql=create_node.sql(dialect="tsql"),
        )

        params: list[IrNode] = []
        for arg in func_def.expressions:
            if isinstance(arg, exp.ColumnDef):
                params.append(self._convert_column_def(arg))
        node.children = params

        return node

    def _convert_select(self, node: exp.Select) -> IrNode:
        ir = IrNode(node_type=IrNodeType.SELECT, original_sql=node.sql(dialect="tsql"))

        columns: list[IrNode] = []
        for arg in node.expressions:
            columns.append(self._expression_to_ir(arg))
        ir.children.extend(columns)

        from_table = node.args.get("from")
        if from_table:
            ir.properties["from"] = from_table.this.sql(dialect="tsql")

        where = node.args.get("where")
        if where:
            ir.children.append(
                IrNode(
                    node_type=IrNodeType.WHERE,
                    children=[self._expression_to_ir(where.this)],
                )
            )

        order = node.args.get("order")
        if order:
            ir.children.append(IrNode(node_type=IrNodeType.ORDER_BY))

        limit = node.args.get("limit")
        if limit:
            ir.children.append(
                IrNode(node_type=IrNodeType.LIMIT, value=limit.sql(dialect="tsql"))
            )

        return ir

    def _convert_insert(self, node: exp.Insert) -> IrNode:
        return IrNode(
            node_type=IrNodeType.INSERT,
            original_sql=node.sql(dialect="tsql"),
        )

    def _convert_update(self, node: exp.Update) -> IrNode:
        return IrNode(
            node_type=IrNodeType.UPDATE,
            original_sql=node.sql(dialect="tsql"),
        )

    def _convert_delete(self, node: exp.Delete) -> IrNode:
        return IrNode(
            node_type=IrNodeType.DELETE,
            original_sql=node.sql(dialect="tsql"),
        )

    def _convert_set(self, node: exp.Set) -> IrNode:
        return IrNode(
            node_type=IrNodeType.SET,
            original_sql=node.sql(dialect="tsql"),
        )

    def _convert_if(self, node: exp.If) -> IrNode:
        return IrNode(
            node_type=IrNodeType.IF,
            original_sql=node.sql(dialect="tsql"),
        )

    def _convert_declare(self, node: exp.Declare) -> IrNode:
        return IrNode(
            node_type=IrNodeType.DECLARE,
            original_sql=node.sql(dialect="tsql"),
        )

    def _convert_block(self, node: exp.Block) -> IrNode:
        children: list[IrNode] = []
        for stmt in node.expressions:
            child = self._convert_statement(stmt)
            if child:
                children.append(child)
        return IrNode(
            node_type=IrNodeType.BLOCK,
            children=children,
            original_sql=node.sql(dialect="tsql"),
        )

    def _convert_column_def(self, node: exp.ColumnDef) -> IrNode:
        return IrNode(
            node_type=IrNodeType.COLUMN_REF,
            value=node.name,
            original_sql=node.sql(dialect="tsql"),
        )

    def _expression_to_ir(self, node: exp.Expression) -> IrNode:
        if isinstance(node, exp.Column):
            return IrNode(
                node_type=IrNodeType.COLUMN_REF,
                value=node.name,
            )
        elif isinstance(node, exp.Literal):
            return IrNode(
                node_type=IrNodeType.LITERAL,
                value=node.output_name if hasattr(node, "output_name") else node.sql(),
            )
        elif isinstance(node, exp.Parameter):
            return IrNode(
                node_type=IrNodeType.PARAMETER,
                value=node.name,
            )
        elif isinstance(node, exp.Func):
            return IrNode(
                node_type=IrNodeType.FUNCTION_CALL,
                value=node.sql_name() if hasattr(node, "sql_name") else node.sql(),
                children=[
                    self._expression_to_ir(a)
                    for a in node.args.get("expressions", [])
                    if isinstance(a, exp.Expression)
                ],
            )
        elif isinstance(node, exp.Binary):
            return IrNode(
                node_type=IrNodeType.BINARY_OP,
                value=type(node).__name__.upper() if hasattr(node, "__class__") else "OP",
                children=[
                    self._expression_to_ir(node.left),
                    self._expression_to_ir(node.right),
                ],
            )
        return IrNode(
            node_type=IrNodeType.LITERAL,
            value=node.sql(dialect="tsql") if hasattr(node, "sql") else str(node),
        )

    def get_warnings(self) -> list[ConversionWarning]:
        return self.warnings
