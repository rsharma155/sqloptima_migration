"""
Domain: Transpilation
Purpose: SQL Server to PostgreSQL conversion modules

Modules:
  - transformation_rule: Rule engine, SyntaxRule, FunctionMappingRule, DataTypeMappingRule
  - ir_models: Intermediate Representation (IR) AST nodes
  - ir_builder: SQLGlot AST -> IR converter
  - type_mappings: Data type mapping definitions
  - type_enhancements: Enhanced type handling (sysname, geometry, numeric optimization, etc.)
  - ddl_generator: IR -> PostgreSQL DDL generator
  - identifier_converter: Case conversion, quoting, snake_case
  - schema_relabeler: Schema remapping (dbo -> public, custom)
  - sql_expression_converter: T-SQL expression/function/default value converter
  - procedural_converter: T-SQL -> PL/pgSQL procedural conversion
  - compatibility_analyzer: Compatibility analysis
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from domains.transpilation.transformation_rule import (
    DataTypeMappingRule,
    FunctionMappingRule,
    RuleCategory,
    RuleRegistry,
    SyntaxRule,
    TransformationEngine,
    TransformationRule,
    SQLSERVER_KEYWORDS,
    register_default_rules,
)
from domains.transpilation.ir_models import (
    ColumnDefNode,
    ConstraintNode,
    DataTypeNode,
    IrNode,
    IrNodeType,
    IrProgram,
)
from domains.transpilation.ir_builder import IrBuilder
from domains.transpilation.type_mappings import (
    DATA_TYPE_MAPPINGS,
    get_type_mapping,
    get_type_mapping_rules,
)
from domains.transpilation.type_enhancements import EnhancedTypeConverter, TypeConversionResult
from domains.transpilation.ddl_generator import DdlGenerator
from domains.transpilation.identifier_converter import (
    CaseTreatment,
    IdentifierConverter,
    MAX_IDENTIFIER_LENGTH,
)
from domains.transpilation.schema_relabeler import SchemaRelabeler
from domains.transpilation.sql_expression_converter import (
    DefaultValueResult,
    TSQL_TO_PG_FUNCTIONS,
    TsqlExpressionConverter,
)
from domains.transpilation.compatibility_analyzer import (
    CompatibilityAnalyzer,
    CompatibilityIssue,
    CompatibilityResult,
)
from domains.transpilation.procedural_converter import (
    CFGNode,
    ControlFlowGraph,
    ControlFlowGraphBuilder,
    ConversionDifficulty,
    ConversionResult,
    DynamicSqlAnalyzer,
    DynamicSqlOccurrence,
    ParameterInfo,
    ProceduralConverter,
    ProceduralObject,
    TSqlPatternMatcher,
    TvpConverter,
    TvpTypeDefinition,
    TvpUsage,
    Variable,
    VariableScopeResolver,
)

__all__ = [
    # Core engine
    "TransformationRule",
    "SyntaxRule",
    "FunctionMappingRule",
    "DataTypeMappingRule",
    "RuleCategory",
    "RuleRegistry",
    "TransformationEngine",
    "SQLSERVER_KEYWORDS",
    "register_default_rules",
    # IR
    "IrNode",
    "IrNodeType",
    "IrProgram",
    "DataTypeNode",
    "ColumnDefNode",
    "ConstraintNode",
    "IrBuilder",
    # Types
    "DATA_TYPE_MAPPINGS",
    "get_type_mapping",
    "get_type_mapping_rules",
    "EnhancedTypeConverter",
    "TypeConversionResult",
    # DDL
    "DdlGenerator",
    # Identifiers
    "IdentifierConverter",
    "CaseTreatment",
    "MAX_IDENTIFIER_LENGTH",
    # Schema
    "SchemaRelabeler",
    # Expressions
    "TsqlExpressionConverter",
    "DefaultValueResult",
    "TSQL_TO_PG_FUNCTIONS",
    # Compatibility
    "CompatibilityAnalyzer",
    "CompatibilityIssue",
    "CompatibilityResult",
    # Procedural
    "ProceduralConverter",
    "ProceduralObject",
    "ParameterInfo",
    "ConversionResult",
    "ConversionDifficulty",
    "TSqlPatternMatcher",
    "DynamicSqlAnalyzer",
    "DynamicSqlOccurrence",
    "TvpConverter",
    "TvpTypeDefinition",
    "TvpUsage",
    "ControlFlowGraph",
    "ControlFlowGraphBuilder",
    "CFGNode",
    "VariableScopeResolver",
    "Variable",
]
