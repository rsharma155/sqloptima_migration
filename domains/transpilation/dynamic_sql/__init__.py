"""
Module: domains/transpilation/dynamic_sql
Purpose: SQL Server dynamic SQL → PostgreSQL conversion toolkit.
         Resolves EXEC/sp_executesql variable concatenation into static SQL
         and generates PL/pgSQL function/procedure wrappers.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from domains.transpilation.dynamic_sql.converter import (
    Converter,
    DynamicSqlProcedureConverter,
)
from domains.transpilation.dynamic_sql.models import (
    ConditionalPredicate,
    ConversionResult as DynamicSqlConversionResult,
    ConversionWarning,
    DynamicSqlStatement,
    FragmentType,
    FunctionKind,
    FunctionParameter,
    IrNode,
    IrNodeType,
    ProcedureNode,
    Severity,
    SqlFragment,
)
from domains.transpilation.dynamic_sql.prepass import (
    apply_dynamic_sql_prepass,
    has_resolvable_dynamic_sql,
)
from domains.transpilation.dynamic_sql.resolver import DynamicSqlResolver
from domains.transpilation.dynamic_sql.symbol_table import SymbolTable

__all__ = [
    "apply_dynamic_sql_prepass",
    "has_resolvable_dynamic_sql",
    "Converter",
    "DynamicSqlProcedureConverter",
    "DynamicSqlConversionResult",
    "ConversionWarning",
    "DynamicSqlResolver",
    "DynamicSqlStatement",
    "FragmentType",
    "FunctionKind",
    "FunctionParameter",
    "IrNode",
    "IrNodeType",
    "Severity",
    "SqlFragment",
    "SymbolTable",
    "ConditionalPredicate",
]
