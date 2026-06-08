"""
Module: converter.py
Purpose: Main orchestrator — converts SQL Server dynamic SQL/procedures
         to PostgreSQL-compatible PL/pgSQL.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import re
from typing import Any

import sqlglot
from sqlglot import exp

from domains.transpilation.dynamic_sql.ir_builder import IrBuilder
from domains.transpilation.dynamic_sql.models import (
    ConditionalPredicate,
    ConversionResult,
    ConversionWarning,
    FragmentType,
    FunctionKind,
    FunctionParameter,
    IrNode,
    IrNodeType,
    ProcedureNode,
    Severity,
    SqlFragment,
)
from domains.transpilation.dynamic_sql.normalizer import SqlNormalizer
from domains.transpilation.dynamic_sql.pg_generator import PgGenerator
from domains.transpilation.dynamic_sql.resolver import DynamicSqlResolver
from domains.transpilation.dynamic_sql.symbol_table import SymbolEntry, SymbolTable
from domains.transpilation.dynamic_sql.type_mapper import FUNCTION_MAPPINGS, TYPE_MAPPINGS, TypeMapper

_CREATE_PROC_PATTERN = re.compile(
    r"CREATE\s+(?:OR\s+ALTER\s+)?PROC(?:EDURE)?\s+(?:(\w+)\.)?(\w+)",
    re.IGNORECASE,
)
_CREATE_FUNC_PATTERN = re.compile(
    r"CREATE\s+(?:OR\s+ALTER\s+)?FUNCTION\s+(?:(\w+)\.)?(\w+)",
    re.IGNORECASE,
)
_PARAM_PATTERN = re.compile(
    r"@(\w+)\s+(\w+(?:\([^)]*\))?(?:\s*(?:=|OUTPUT|OUT|READONLY))?)",
    re.IGNORECASE,
)
_VARIABLE_DECLARE = re.compile(
    r"DECLARE\s+@(\w+)\s+(?:AS\s+)?(\w+(?:\([^)]*\))?)",
    re.IGNORECASE,
)
_SET_PATTERN = re.compile(
    r"SET\s+@(\w+)\s*=\s*(.+)",
    re.IGNORECASE,
)
_SET_PLUS_PATTERN = re.compile(
    r"SET\s+@(\w+)\s*\+=\s*(.+)",
    re.IGNORECASE,
)
_IF_CONDITION_PATTERN = re.compile(
    r"IF\s+(@\w+)\s+(IS\s+NOT\s+NULL|IS\s+NULL|=|<>|!=|>|<|>=|<=)\s*(.*)",
    re.IGNORECASE,
)
_EXEC_PATTERN = re.compile(
    r"(?:EXEC|EXECUTE)\s*(?:\(|@?[\w]+)",
    re.IGNORECASE,
)
_SP_EXECUTESQL_PATTERN = re.compile(
    r"sp_executesql\s",
    re.IGNORECASE,
)


class DynamicSqlProcedureConverter:
    """Orchestrator that converts SQL Server dynamic SQL to PostgreSQL."""

    def __init__(self):
        self.symbol_table = SymbolTable()
        self.resolver = DynamicSqlResolver(self.symbol_table)
        self.normalizer = SqlNormalizer(self.symbol_table)
        self.ir_builder = IrBuilder()
        self.pg_generator = PgGenerator()
        self.type_mapper = TypeMapper()

    def convert_sql(self, tsql: str) -> ConversionResult:
        """Convert a T-SQL string (procedure, function, or standalone SQL) to PostgreSQL."""
        result = ConversionResult(success=False)
        result.source_sql = tsql

        if not tsql or not tsql.strip():
            result.errors.append("Empty input SQL")
            return result

        try:
            procedure = self._extract_procedure_info(tsql)
            if procedure:
                result.procedure_name = f"{procedure.schema_name}.{procedure.name}"

            body_sql = self._extract_body(tsql)
            self._build_symbol_table(body_sql, tsql)
            normalized_body = self._resolve_dynamic_sql(body_sql)
            result.normalized_sql = normalized_body

            ir_tree = self.ir_builder.build(normalized_body)
            has_ir_parse_errors = any(
                w.code == "PARSE_FAILURE" for w in self.ir_builder.get_warnings()
            )

            if procedure:
                ir_tree = self._wrap_in_function(ir_tree, procedure)

            pg_sql = self.pg_generator.generate(ir_tree)
            result.target_sql = pg_sql
            result.success = True

            body_is_empty = self._generated_body_is_empty(pg_sql)
            if procedure and (body_is_empty or has_ir_parse_errors):
                result.target_sql = self._generate_procedure_wrapper(
                    procedure, normalized_body
                )
                result.success = True

        except Exception as e:
            result.errors.append(f"Conversion error: {e}")

        result.warnings.extend(
            self.resolver.get_warnings()
            + self.normalizer.get_warnings()
            + self.ir_builder.get_warnings()
            + self.pg_generator.get_warnings()
            + self.type_mapper.get_warnings()
        )

        return result

    def _extract_procedure_info(self, tsql: str) -> ProcedureNode | None:
        """Extract procedure/function name, schema, and parameters from DDL header."""
        tsql_clean = tsql.strip()
        if tsql_clean.startswith("--"):
            tsql_clean = re.sub(r"^--.*?(?:\n|$)", "", tsql_clean, flags=re.MULTILINE)
        tsql_clean = tsql_clean.strip()

        create_match = _CREATE_PROC_PATTERN.search(tsql_clean)
        is_function = False
        if not create_match:
            create_match = _CREATE_FUNC_PATTERN.search(tsql_clean)
            is_function = True

        if not create_match:
            return None

        schema = create_match.group(1) or "dbo"
        name = create_match.group(2)

        func_start = create_match.end()
        as_match = re.search(
            r"\bAS\b",
            tsql_clean[func_start:],
            re.IGNORECASE,
        )
        params_str = ""
        if as_match:
            params_str = tsql_clean[func_start : func_start + as_match.start()].strip()

        params: list[FunctionParameter] = []
        if params_str and not params_str.upper().startswith("AS"):
            param_matches = _PARAM_PATTERN.findall(params_str)
            for p in param_matches:
                pname, ptype = p[0], p[1].strip().rstrip("=").strip()
                params.append(
                    FunctionParameter(name=pname, data_type=ptype)
                )
                self.symbol_table.add_procedure_param(f"@{pname}", ptype)

        procedure = ProcedureNode(
            schema_name=schema,
            name=name,
            parameters=params,
            kind=FunctionKind.FUNCTION if is_function else FunctionKind.PROCEDURE,
        )
        self.symbol_table.set_procedure_info(schema, name)
        return procedure

    def _extract_body(self, tsql: str) -> str:
        """Extract the procedure body between AS ... BEGIN ... END."""
        tsql_clean = tsql.strip()
        if tsql_clean.startswith("--"):
            tsql_clean = re.sub(r"^--.*?(?:\n|$)", "", tsql_clean, flags=re.MULTILINE)

        body = tsql_clean

        as_match = re.search(r"\bAS\b", body, re.IGNORECASE)
        if as_match:
            body = body[as_match.end():].strip()

        begin_match = re.search(r"\bBEGIN\b", body, re.IGNORECASE)
        end_match = re.search(r"\bEND\s*$", body, re.IGNORECASE)

        if begin_match and end_match:
            body = body[begin_match.end():end_match.start()].strip()
        elif begin_match:
            body = body[begin_match.end():].strip()

        return body

    def _build_symbol_table(self, body_sql: str, full_tsql: str) -> None:
        """Track all variable declarations and assignments for dynamic SQL analysis."""
        for d in _VARIABLE_DECLARE.finditer(body_sql):
            var_name = "@" + d.group(1)
            var_type = d.group(2)
            self.symbol_table.declare(var_name, var_type)
            entry = self.symbol_table.get(var_name)
            if entry:
                entry.is_dynamic_sql = "NVARCHAR" in var_type.upper() or "VARCHAR" in var_type.upper()

        lines = body_sql.split("\n")
        current_if_condition: str | None = None
        current_if_var: str | None = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if_match = _IF_CONDITION_PATTERN.search(line)
            if if_match:
                current_if_var = if_match.group(1)
                current_if_condition = (if_match.group(2) + " " + if_match.group(3)).strip()
                continue

            set_plus = _SET_PLUS_PATTERN.search(line)
            if set_plus:
                var_name = "@" + set_plus.group(1)
                expr = set_plus.group(2).strip().rstrip(";")
                entry = self.symbol_table.get(var_name)
                if entry:
                    self._parse_expression_into_entry(entry, expr)
                    self._record_if_condition(entry, current_if_var, current_if_condition, expr)
                current_if_condition = None
                current_if_var = None
                continue

            set_eq = _SET_PATTERN.search(line)
            if set_eq:
                var_name = "@" + set_eq.group(1)
                expr = set_eq.group(2).strip().rstrip(";")
                entry = self.symbol_table.get(var_name)
                if entry:
                    self_ref = re.match(
                        r"@(\w+)\s*\+{1,2}\s*(.+)", expr, re.IGNORECASE
                    )
                    if self_ref and "@" + self_ref.group(1) == var_name:
                        self._parse_expression_into_entry(entry, self_ref.group(2).strip())
                        self._record_if_condition(entry, current_if_var, current_if_condition, self_ref.group(2).strip())
                    else:
                        entry.fragments.clear()
                        self._parse_expression_into_entry(entry, expr)
                        self._record_if_condition(entry, current_if_var, current_if_condition, expr)
                current_if_condition = None
                current_if_var = None
                continue

    def _record_if_condition(
        self,
        entry: SymbolEntry,
        if_var: str | None,
        if_condition: str | None,
        expr: str,
    ) -> None:
        """Store IF condition on the dynamic SQL variable entry for later resolution."""
        if if_var and if_condition and entry and entry.is_dynamic_sql:
            entry.conditional_predicates.append(
                ConditionalPredicate(
                    variable=if_var,
                    condition=if_condition,
                    sql_fragment=expr,
                )
            )

    def _parse_expression_into_entry(
        self, entry: SymbolEntry, expr: str
    ) -> None:
        """Parse a SET expression into individual SQL fragments."""
        expr = expr.strip()

        if expr.startswith("'") or expr.startswith("N'"):
            text = expr
            if text.upper().startswith("N'"):
                text = text[1:]
            if text.startswith("'") and text.endswith("'"):
                text = text[1:-1]
            entry.add_literal(text)
            return

        parts = re.split(r"(\s*\+{1,2}\s*)", expr)
        current_text: list[str] = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if part in ("+", "++"):
                if current_text:
                    joined = "".join(current_text)
                    self._emit_fragment(entry, joined)
                    current_text = []
                continue

            cast_match = re.match(
                r"CAST\s*\(\s*(@\w+)\s*AS\s+\w+(?:\([^)]*\))?\s*\)",
                part,
                re.IGNORECASE,
            )
            if cast_match:
                if current_text:
                    joined = "".join(current_text)
                    self._emit_fragment(entry, joined)
                    current_text = []
                entry.add_variable(cast_match.group(1))
                continue

            var_ref = re.match(r"^@(\w+)$", part)
            if var_ref:
                if current_text:
                    joined = "".join(current_text)
                    self._emit_fragment(entry, joined)
                    current_text = []
                entry.add_variable("@" + var_ref.group(1))
                continue

            if part.startswith("'") or part.startswith("N'"):
                text = part
                if text.upper().startswith("N'"):
                    text = text[1:]
                if text.startswith("'") and text.endswith("'"):
                    text = text[1:-1]
                current_text.append(text)
            else:
                current_text.append(part)

        if current_text:
            joined = "".join(current_text)
            self._emit_fragment(entry, joined)

    def _emit_fragment(self, entry: SymbolEntry, text: str) -> None:
        """Emit a literal segment to the entry, or detect inline variables."""
        var_positions = [
            (m.start(), m.end(), m.group())
            for m in re.finditer(r"@\w+", text)
        ]
        if not var_positions:
            entry.add_literal(text)
            return

        prev_end = 0
        for start, end, var_name in var_positions:
            if start > prev_end:
                entry.add_literal(text[prev_end:start])
            entry.add_variable(var_name)
            prev_end = end
        if prev_end < len(text):
            entry.add_literal(text[prev_end:])

    def _resolve_dynamic_sql(self, body_sql: str) -> str:
        """Replace EXEC/sp_executesql calls with their resolved static SQL."""
        lines = body_sql.split("\n")
        resolved_lines: list[str] = []

        for line in lines:
            stripped = line.strip()

            if _SP_EXECUTESQL_PATTERN.search(stripped) or _EXEC_PATTERN.search(stripped):
                stmt = self.resolver.resolve_statement(stripped)
                if stmt.normalized_sql:
                    normalized = self.normalizer.normalize(stmt.normalized_sql)
                    resolved_lines.append(normalized)
                else:
                    resolved_lines.append(stripped)
            else:
                resolved_lines.append(line)

        return "\n".join(resolved_lines)

    def _wrap_in_function(
        self, ir_tree: IrNode, procedure: ProcedureNode
    ) -> IrNode:
        """Wrap IR tree in a CREATE FUNCTION node."""
        func_node = IrNode(
            node_type=IrNodeType.CREATE_FUNCTION,
            properties={
                "schema": procedure.schema_name,
                "name": procedure.name,
                "full_name": f"{procedure.schema_name}.{procedure.name}",
                "parameters": [
                    {"name": p.name, "type": p.data_type}
                    for p in procedure.parameters
                ],
            },
        )
        func_node.children.append(ir_tree)
        return func_node

    def _generated_body_is_empty(self, pg_sql: str) -> bool:
        """Check if the generated PostgreSQL function body is effectively empty."""
        body_start = pg_sql.find("BEGIN")
        body_end = pg_sql.find("END;", body_start) if body_start >= 0 else -1
        if body_start >= 0 and body_end >= 0:
            body = pg_sql[body_start + 5 : body_end].strip()
            return not body
        return False

    def _generate_procedure_wrapper(
        self, procedure: ProcedureNode, normalized_body: str
    ) -> str:
        """Directly generate a PostgreSQL function wrapper for simple cases."""
        lines: list[str] = []
        params: list[str] = []
        for p in procedure.parameters:
            pg_type = self.type_mapper.map_data_type(p.data_type)
            pg_type = re.sub(r"\s*OUTPUT\s*", "", pg_type, flags=re.IGNORECASE).strip()
            params.append(f"    p_{p.name} {pg_type}")

        lines.append(
            f"CREATE OR REPLACE FUNCTION {procedure.schema_name}.{procedure.name}("
        )
        lines.append(",".join(params))
        lines.append(")")
        lines.append("RETURNS SETOF RECORD")
        lines.append("LANGUAGE plpgsql")
        lines.append("AS $$")
        lines.append("BEGIN")

        body = self._convert_body_to_plpgsql(normalized_body)
        for line in body.split("\n"):
            lines.append(f"    {line}")

        lines.append("END;")
        lines.append("$$;")
        result = "\n".join(lines)
        result = re.sub(
            r"sp_executesql\s+@\w+\s*,?\s*@?\w*[^;]*;",
            "-- EXEC converted: see normalized body above",
            result,
            flags=re.IGNORECASE,
        )
        result = re.sub(
            r"\bEXEC\b\s*[@(][^;]*;",
            "-- EXEC converted: see normalized body above",
            result,
            flags=re.IGNORECASE,
        )
        result = re.sub(r"\bGO\b", "", result, flags=re.IGNORECASE)
        return result

    def _convert_body_to_plpgsql(self, body: str) -> str:
        result = body
        result = re.sub(
            r"^\s*SET\s+NOCOUNT\s+ON\s*;?\s*$",
            "",
            result,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        result = re.sub(
            r"^\s*SET\s+XACT_ABORT\s+ON\s*;?\s*$",
            "",
            result,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        result = re.sub(r"^\s*GO\s*$", "", result, flags=re.MULTILINE)
        result = re.sub(r"\bN'", "'", result)
        result = re.sub(
            r"\bPRINT\s+(.+?);",
            r"RAISE NOTICE '%', \1;",
            result,
            flags=re.IGNORECASE,
        )
        result = re.sub(
            r"\bRAISERROR\s*\(([^,]+),\s*\d+,\s*\d+(?:,\s*([^)]+))?\)",
            r"RAISE EXCEPTION '\1', \2",
            result,
            flags=re.IGNORECASE,
        )
        result = re.sub(r"@(\w+)", r"\1", result)
        result = re.sub(
            r"\bOUTPUT\b", "RETURNING", result, flags=re.IGNORECASE
        )
        result = re.sub(
            r"\bTOP\s+(\d+)", r"LIMIT \1", result, flags=re.IGNORECASE
        )
        result = re.sub(r"\[(\w+)\]", r"\1", result)
        result = re.sub(
            r"\bWITH\s*\(\s*(NOLOCK|READUNCOMMITTED|UPDLOCK|TABLOCK|TABLOCKX|ROWLOCK|PAGLOCK|NOWAIT|SERIALIZABLE|REPEATABLEREAD|READCOMMITTED)\s*\)",
            "",
            result,
            flags=re.IGNORECASE,
        )
        result = re.sub(
            r"\bGETDATE\(\)", "CURRENT_TIMESTAMP", result, flags=re.IGNORECASE
        )
        result = re.sub(
            r"\bNEWID\(\)", "gen_random_uuid()", result, flags=re.IGNORECASE
        )
        result = re.sub(r"^\s*;\s*$", "", result, flags=re.MULTILINE)
        lines = result.split("\n")
        cleaned: list[str] = []
        for line in lines:
            stripped = line.strip()
            if re.match(
                r"^\s*(?:EXEC|EXECUTE|sp_executesql)\s",
                stripped,
                re.IGNORECASE,
            ):
                cleaned.append(f"    -- {stripped}  -- requires manual review")
            else:
                cleaned.append(line)
        result = "\n".join(cleaned)
        result = self._map_types_and_functions(result)
        result = result.strip()
        return result

    def _map_types_and_functions(self, sql: str) -> str:
        """Apply function and type mappings."""
        result = sql
        for tsql_func, pg_func in sorted(
            FUNCTION_MAPPINGS.items(), key=lambda x: -len(x[0])
        ):
            pattern = re.compile(
                r"\b" + re.escape(tsql_func) + r"\s*\(", re.IGNORECASE
            )
            result = pattern.sub(pg_func + "(", result)
        for tsql_type, pg_type in sorted(
            TYPE_MAPPINGS.items(), key=lambda x: -len(x[0])
        ):
            pattern = re.compile(
                r"\b" + re.escape(tsql_type) + r"\b", re.IGNORECASE
            )
            result = pattern.sub(pg_type, result)
        return result


# Backward-compatible alias used in tests and batch tooling.
Converter = DynamicSqlProcedureConverter
