"""
Module: ir_builder.py
Purpose: Converts SQLGlot AST into Normalized Intermediate Representation (IR)
Author: Migration Platform Team
Created: 2026-05-22
Domain: Transpilation
Dependencies: sqlglot
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

import contextlib
from typing import Any

from sqlglot import exp

from domains.parsing.sqlglot_adapter import SqlglotParser
from domains.transpilation.ir_models import (
    ColumnDefNode,
    ConstraintNode,
    DataTypeNode,
    IrNode,
    IrNodeType,
    IrProgram,
)


class IrBuilder:
    """Converts SQLGlot AST trees into normalized IR trees.

    This is the bridge between the parser and the transformation engine.
    The IR abstracts away dialect-specific AST details into a generic
    representation that transformation rules can operate on.
    """

    def __init__(self, parser: SqlglotParser):
        self._parser = parser

    def build_from_sql(self, sql: str) -> IrProgram | None:
        """Parse SQL and build IR tree."""
        result = self._parser.parse(sql)
        if not result.success or result.ast is None:
            return None
        return self.build(result.ast)

    def build(self, ast: exp.Expression) -> IrProgram:
        """Build IR tree from a SQLGlot AST node."""
        program = IrProgram()
        if isinstance(ast, exp.Query):
            program.statements.append(self._build_query(ast))
        elif isinstance(ast, exp.DDL):
            ddl_nodes = self._build_ddl(ast)
            program.statements.extend(ddl_nodes)
        elif isinstance(ast, exp.CTE):
            program.statements.append(self._build_cte(ast))
        else:
            generic = self._generic_node(ast)
            if generic:
                program.statements.append(generic)
        return program

    def build_multiple(self, sql: str) -> IrProgram:
        """Build IR from multiple SQL statements."""
        results = self._parser.parse_multiple(sql)
        program = IrProgram()
        for result in results:
            if result.success and result.ast is not None:
                sub = self.build(result.ast)
                program.statements.extend(sub.statements)
        return program

    def _build_query(self, node: exp.Query) -> IrNode:
        ir = IrNode(node_type=IrNodeType.SELECT)
        ir.properties["sql"] = node.sql()
        if isinstance(node, exp.Select):
            for arg_key, arg_val in node.args.items():
                if arg_val is not None:
                    ir.properties[arg_key] = self._convert_arg(arg_val)
        return ir

    def _build_ddl(self, node: exp.DDL) -> list[IrNode]:
        nodes: list[IrNode] = []

        if isinstance(node, exp.Create):
            kind = node.args.get("kind", "")
            if kind == "TABLE":
                table_node = self._build_create_table(node)
                nodes.append(table_node)
            elif kind == "VIEW":
                view_node = IrNode(node_type=IrNodeType.CREATE_VIEW)
                view_node.properties["name"] = self._extract_name(node)
                nodes.append(view_node)
            elif kind == "INDEX":
                idx_node = IrNode(node_type=IrNodeType.CREATE_INDEX)
                idx_node.properties["name"] = self._extract_name(node)
                nodes.append(idx_node)

        return nodes

    def _build_create_table(self, node: exp.Create) -> IrNode:
        ir = IrNode(node_type=IrNodeType.CREATE_TABLE)
        ir.properties["name"] = self._extract_name(node)
        ir.properties["schema"] = self._extract_schema(node)
        ir.properties["if_not_exists"] = node.args.get("exists", False)

        columns: list[ColumnDefNode] = []
        constraints: list[ConstraintNode] = []

        expressions = []
        if isinstance(node.this, exp.Schema):
            expressions = node.this.expressions or []

        for expr in expressions:
            if isinstance(expr, exp.ColumnDef):
                col = self._build_column_def(expr)
                if col:
                    columns.append(col)
            elif isinstance(expr, exp.Constraint):
                constraint = self._build_constraint(expr)
                if constraint:
                    constraints.append(constraint)

        ir.children = columns  # type: ignore
        ir.properties["constraints"] = constraints
        return ir

    def _build_column_def(self, node: exp.ColumnDef) -> ColumnDefNode | None:
        try:
            col = ColumnDefNode(column_name=node.name)
            col.properties["sql"] = node.sql()

            kind = node.args.get("kind")
            if kind:
                col.data_type = self._build_data_type(kind)

            for constraint in node.constraints:
                if isinstance(constraint, exp.NotNullColumnConstraint):
                    col.is_nullable = False
                elif isinstance(constraint, exp.PrimaryKeyColumnConstraint):
                    col.is_primary_key = True

            return col
        except Exception:
            return None

    def _build_data_type(self, node: exp.DataType) -> DataTypeNode | None:
        try:
            raw_name = (node.this.value if node.this else node.name) or ""
            dt = DataTypeNode(
                type_name=raw_name.upper(),
                is_nullable=True,
            )
            # Extract type parameters (precision, scale, length)
            if hasattr(node, "expressions") and node.expressions:
                for i, expr in enumerate(node.expressions):
                    if isinstance(expr, exp.Literal):
                        val = expr.name
                        if i == 0:
                            try:
                                dt.precision = int(val)
                            except ValueError:
                                dt.max_length = self._parse_length(val)
                        elif i == 1:
                            with contextlib.suppress(ValueError):
                                dt.scale = int(val)
            return dt
        except Exception:
            return None

    def _build_constraint(self, node: exp.Constraint) -> ConstraintNode | None:
        try:
            kind = node.args.get("kind")
            if kind is None:
                return None

            c = ConstraintNode(constraint_name=node.name or "")

            if isinstance(kind, exp.PrimaryKey):
                c.constraint_type = "PRIMARY KEY"
                c.columns = self._extract_column_names(kind)
            elif isinstance(kind, exp.ForeignKey):
                c.constraint_type = "FOREIGN KEY"
                c.columns = self._extract_column_names(kind)
            elif isinstance(kind, exp.UniqueColumnConstraint):
                c.constraint_type = "UNIQUE"
                c.columns = [node.name] if node.name else []
            elif isinstance(kind, exp.CheckColumnConstraint):
                c.constraint_type = "CHECK"
                c.check_expression = kind.sql()

            return c
        except Exception:
            return None

    def _build_cte(self, node: exp.CTE) -> IrNode:
        ir = IrNode(node_type=IrNodeType.SUBQUERY)
        ir.properties["name"] = node.alias_or_name if hasattr(node, "alias_or_name") else ""
        return ir

    def _generic_node(self, node: exp.Expression) -> IrNode | None:
        try:
            ir = IrNode(node_type=IrNodeType.STATEMENT_LIST)
            ir.properties["sql"] = node.sql()
            ir.properties["type"] = type(node).__name__
            return ir
        except Exception:
            return None

    def _convert_arg(self, arg: Any) -> Any:
        """Convert an AST argument to a serializable form."""
        if isinstance(arg, exp.Expression):
            return {"type": type(arg).__name__, "sql": arg.sql()}
        if isinstance(arg, list):
            return [self._convert_arg(a) for a in arg]
        return str(arg)

    @staticmethod
    def _extract_name(node: exp.DDL) -> str:
        try:
            if isinstance(node.this, exp.Schema) and isinstance(node.this.this, exp.Table):
                return node.this.this.name or ""
            if isinstance(node.this, exp.Table):
                return node.this.name or ""
            return node.this.name if hasattr(node.this, "name") else ""
        except Exception:
            return ""

    @staticmethod
    def _extract_schema(node: exp.DDL) -> str:
        try:
            if isinstance(node.this, exp.Schema) and isinstance(node.this.this, exp.Table):
                db = node.this.this.args.get("db")
                return str(db) if db else ""
            if isinstance(node.this, exp.Table):
                db = node.this.args.get("db")
                return str(db) if db else ""
            return ""
        except Exception:
            return ""

    @staticmethod
    def _extract_column_names(node: exp.Expression) -> list[str]:
        cols = node.args.get("expressions") or node.args.get("columns") or []
        return [c.name for c in cols if hasattr(c, "name")]

    @staticmethod
    def _parse_length(val: str) -> int | None:
        val = val.strip()
        if val == "max":
            return -1
        try:
            return int(val)
        except ValueError:
            return None
