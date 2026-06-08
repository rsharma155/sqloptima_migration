"""
Module: pg_generator.py
Purpose: Generates PostgreSQL-compatible PL/pgSQL code from the IR tree.
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
    FunctionKind,
    IrNode,
    IrNodeType,
    ProcedureNode,
    Severity,
)
from domains.transpilation.dynamic_sql.type_mapper import TYPE_MAPPINGS, FUNCTION_MAPPINGS, TypeMapper

_TABLE_HINT_PATTERN = re.compile(
    r"\bWITH\s*\(\s*(NOLOCK|READUNCOMMITTED|READCOMMITTED|SERIALIZABLE|UPDLOCK|TABLOCK|TABLOCKX|NOWAIT|ROWLOCK|PAGLOCK)\s*\)",
    re.IGNORECASE,
)
_TOP_PATTERN = re.compile(r"\bTOP\s+(\d+)\b", re.IGNORECASE)
_SQUARE_BRACKETS = re.compile(r"\[(\w+)\]")
_IDENTITY_INSERT_PATTERN = re.compile(
    r"SET\s+IDENTITY_INSERT\s+\w+\s+(ON|OFF)", re.IGNORECASE
)


class PgGenerator:
    """Generates PostgreSQL-compatible SQL from an IR tree."""

    def __init__(self):
        self.warnings: list[ConversionWarning] = []
        self.type_mapper = TypeMapper()
        self._indent_level = 0
        self._output_lines: list[str] = []

    def generate(self, ir_node: IrNode) -> str:
        """Generate PostgreSQL code from an IR node."""
        self._output_lines = []
        self._indent_level = 0

        if ir_node.node_type == IrNodeType.PROGRAM:
            for child in ir_node.children:
                line = self._generate_node(child)
                if line:
                    self._output_lines.append(line)
        elif ir_node.node_type == IrNodeType.CREATE_FUNCTION:
            return self._generate_function_wrapper(ir_node)
        else:
            line = self._generate_node(ir_node)
            if line:
                self._output_lines.append(line)

        return "\n".join(self._output_lines)

    def _generate_node(self, node: IrNode) -> str:
        handler = {
            IrNodeType.PROGRAM: self._generate_program,
            IrNodeType.SELECT: self._generate_select,
            IrNodeType.INSERT: self._generate_insert,
            IrNodeType.UPDATE: self._generate_update,
            IrNodeType.DELETE: self._generate_delete,
            IrNodeType.SET: self._generate_set,
            IrNodeType.IF: self._generate_if,
            IrNodeType.DECLARE: self._generate_declare,
            IrNodeType.RETURN: self._generate_return,
            IrNodeType.BLOCK: self._generate_block,
            IrNodeType.ASSIGNMENT: self._generate_assignment,
            IrNodeType.EXEC: self._generate_exec,
        }
        handler_fn = handler.get(node.node_type)
        if handler_fn:
            return handler_fn(node)
        return node.original_sql or ""

    def _generate_program(self, node: IrNode) -> str:
        lines: list[str] = []
        for child in node.children:
            line = self._generate_node(child)
            if line:
                lines.append(line)
        return "\n".join(lines)

    def _generate_select(self, node: IrNode) -> str:
        sql = node.original_sql or ""
        sql = self._apply_transformations(sql)
        return sql

    def _generate_insert(self, node: IrNode) -> str:
        sql = node.original_sql or ""
        sql = self._apply_transformations(sql)
        return sql

    def _generate_update(self, node: IrNode) -> str:
        sql = node.original_sql or ""
        sql = self._apply_transformations(sql)
        return sql

    def _generate_delete(self, node: IrNode) -> str:
        sql = node.original_sql or ""
        sql = self._apply_transformations(sql)
        return sql

    def _generate_set(self, node: IrNode) -> str:
        sql = node.original_sql or ""
        sql = self._apply_transformations(sql)
        return sql

    def _generate_if(self, node: IrNode) -> str:
        sql = node.original_sql or ""
        sql = self._apply_transformations(sql)
        return sql

    def _generate_declare(self, node: IrNode) -> str:
        """Convert T-SQL DECLARE to PostgreSQL variable declaration."""
        sql = node.original_sql or ""
        sql = re.sub(
            r"DECLARE\s+@(\w+)\s+AS\s+(\w+(?:\([^)]*\))?)",
            r"\1 \2",
            sql,
            flags=re.IGNORECASE,
        )
        sql = re.sub(
            r"DECLARE\s+@(\w+)\s+(\w+(?:\([^)]*\))?)",
            r"\1 \2",
            sql,
            flags=re.IGNORECASE,
        )
        sql = self._apply_transformations(sql)
        return sql

    def _generate_return(self, node: IrNode) -> str:
        sql = node.original_sql or "RETURN"
        sql = re.sub(r"\bRETURN\b", "RETURN", sql, flags=re.IGNORECASE)
        return sql

    def _generate_block(self, node: IrNode) -> str:
        if node.children:
            lines: list[str] = []
            for child in node.children:
                line = self._generate_node(child)
                if line:
                    lines.append(line)
            return "\n".join(lines)
        if node.value:
            sql = str(node.value)
            sql = self._apply_transformations(sql)
            return sql
        return ""

    def _generate_assignment(self, node: IrNode) -> str:
        sql = node.original_sql or ""
        sql = self._apply_transformations(sql)
        return sql

    def _generate_exec(self, node: IrNode) -> str:
        return f"-- EXEC converted: {node.original_sql}"

    def _generate_function_wrapper(self, node: IrNode) -> str:
        """Wrap the converted body in CREATE OR REPLACE FUNCTION."""
        props = node.properties
        schema = props.get("schema", "public")
        name = props.get("name", "unknown")
        full_name = props.get("full_name", name)

        body_parts: list[str] = []
        for child in node.children:
            line = self._generate_node(child)
            if line:
                body_parts.append(line)

        body_sql = "\n".join(body_parts)
        body_sql = self._apply_transformations(body_sql)

        lines: list[str] = []
        lines.append(f"CREATE OR REPLACE FUNCTION {schema}.{name}(")
        lines.append(")")
        lines.append("RETURNS SETOF RECORD")
        lines.append("LANGUAGE plpgsql")
        lines.append("AS $$")
        lines.append("BEGIN")
        lines.append(f"    {body_sql}")
        lines.append("END;")
        lines.append("$$;")

        return "\n".join(lines)

    def _apply_transformations(self, sql: str) -> str:
        """Apply dialect transformations from T-SQL to PostgreSQL."""
        result = sql

        result = _SQUARE_BRACKETS.sub(r"\1", result)
        result = _TABLE_HINT_PATTERN.sub("", result)
        result = _TOP_PATTERN.sub(r"LIMIT \1", result)
        result = _IDENTITY_INSERT_PATTERN.sub("", result)
        result = re.sub(r"\bPRINT\s+", "RAISE NOTICE '", result, flags=re.IGNORECASE)
        result = re.sub(r"\bOUTPUT\b", "RETURNING", result, flags=re.IGNORECASE)
        result = re.sub(r"\bGETDATE\(\)", "CURRENT_TIMESTAMP", result, flags=re.IGNORECASE)
        result = re.sub(
            r"\bNEWID\(\)", "gen_random_uuid()", result, flags=re.IGNORECASE
        )
        result = re.sub(
            r"\bISNULL\s*\(", "COALESCE(", result, flags=re.IGNORECASE
        )
        result = re.sub(
            r"\bLEN\s*\(", "LENGTH(", result, flags=re.IGNORECASE
        )
        result = re.sub(
            r"\bCHARINDEX\s*\(", "POSITION(", result, flags=re.IGNORECASE
        )
        result = re.sub(
            r"\bIIF\s*\(([^,]+),([^,]+),([^)]+)\)",
            r"CASE WHEN \1 THEN \2 ELSE \3 END",
            result,
            flags=re.IGNORECASE,
        )
        result = re.sub(
            r"\bDATEPART\s*\((\w+)\s*,\s*(.+?)\)",
            r"EXTRACT(\1 FROM \2)",
            result,
            flags=re.IGNORECASE,
        )

        result = result.strip()
        return result

    def get_warnings(self) -> list[ConversionWarning]:
        return self.warnings
