"""
Module: transformation_rule.py
Purpose: Rule-based transformation engine for AST-to-AST conversions
Author: Migration Platform Team
Created: 2026-05-22
Domain: Transpilation
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class RuleCategory(str):
    SYNTAX = "syntax"
    DATATYPE = "datatype"
    FUNCTION = "function"
    PROCEDURE = "procedure"
    INDEX = "index"
    SEMANTIC = "semantic"
    RUNTIME = "runtime"
    ARCHITECTURE = "architecture"


class TransformationRule(BaseModel, ABC):
    """Base class for all transformation rules."""

    rule_id: UUID = Field(default_factory=uuid4)
    name: str
    category: str
    version: str = "1.0.0"
    description: str = ""
    enabled: bool = True

    @abstractmethod
    def match(self, node: Any) -> bool:
        """Check if this rule applies to the given AST/IR node."""

    @abstractmethod
    def apply(self, node: Any) -> Any:
        """Apply the transformation to the node. Returns transformed node."""


class SyntaxRule(TransformationRule):
    """Rule for syntax-level transformations (e.g., TOP → LIMIT)."""

    pattern: str = ""
    replacement_template: str = ""

    def match(self, node: Any) -> bool:
        from domains.transpilation.ir_models import IrNode
        if isinstance(node, IrNode):
            return node.node_type.value == self.pattern
        return False

    def apply(self, node: Any) -> Any:
        return node


class FunctionMappingRule(TransformationRule):
    """Rule for function name mappings (e.g., ISNULL → COALESCE)."""

    source_function: str = ""
    target_function: str = ""
    arg_transform: str | None = None

    def match(self, node: Any) -> bool:
        from sqlglot import exp
        if isinstance(node, exp.Func):
            return node.name.upper() == self.source_function.upper()
        return False

    def apply(self, node: Any) -> Any:
        from sqlglot import exp
        if isinstance(node, exp.Func):
            new = exp.Anonymous(this=self.target_function, expressions=node.expressions)
            return new
        return node


class DataTypeMappingRule(TransformationRule):
    """Rule for data type mappings (e.g., UNIQUEIDENTIFIER → UUID)."""

    source_type: str = ""
    target_type: str = ""
    target_precision: int | None = None
    target_scale: int | None = None

    def match(self, node: Any) -> bool:
        from domains.transpilation.ir_models import DataTypeNode
        if isinstance(node, DataTypeNode):
            return node.type_name.upper() == self.source_type.upper()
        return False

    def apply(self, node: Any) -> Any:
        from domains.transpilation.ir_models import DataTypeNode
        if isinstance(node, DataTypeNode):
            return DataTypeNode(
                type_name=self.target_type,
                precision=self.target_precision,
                scale=self.target_scale,
                max_length=node.max_length,
                is_nullable=node.is_nullable,
            )
        return node


class RuleRegistry:
    """Registry of all transformation rules with versioning."""

    def __init__(self):
        self._rules: dict[str, list[TransformationRule]] = {}
        self._all_rules: dict[UUID, TransformationRule] = {}

    def register(self, rule: TransformationRule) -> None:
        """Register a rule in the registry."""
        self._all_rules[rule.rule_id] = rule
        category = rule.category
        if category not in self._rules:
            self._rules[category] = []
        self._rules[category].append(rule)

    def register_many(self, rules: list[TransformationRule]) -> None:
        """Register multiple rules."""
        for rule in rules:
            self.register(rule)

    def get_by_category(self, category: str) -> list[TransformationRule]:
        """Get all rules for a given category."""
        return self._rules.get(category, [])

    def get_all(self) -> list[TransformationRule]:
        """Get all registered rules."""
        return list(self._all_rules.values())

    def get_by_name(self, name: str) -> TransformationRule | None:
        """Find a rule by name."""
        for rule in self._all_rules.values():
            if rule.name == name:
                return rule
        return None

    def remove(self, rule_id: UUID) -> None:
        """Remove a rule by ID."""
        rule = self._all_rules.pop(rule_id, None)
        if rule:
            category_rules = self._rules.get(rule.category, [])
            self._rules[rule.category] = [r for r in category_rules if r.rule_id != rule_id]

    def clear(self) -> None:
        """Clear all rules."""
        self._all_rules.clear()
        self._rules.clear()

    @property
    def count(self) -> int:
        return len(self._all_rules)


class TransformationEngine:
    """AST transformation engine that applies registered rules."""

    def __init__(self, registry: RuleRegistry | None = None):
        self._registry = registry or RuleRegistry()
        self._pre_hooks: list[callable] = []
        self._post_hooks: list[callable] = []

    @property
    def registry(self) -> RuleRegistry:
        return self._registry

    def transform(self, ir_program: Any) -> Any:
        """Apply all enabled rules to an IR program tree."""
        if hasattr(ir_program, "statements"):
            transformed = []
            for stmt in ir_program.statements:
                transformed.append(self._transform_node(stmt))
            ir_program.statements = transformed
        return ir_program

    def _transform_node(self, node: Any) -> Any:
        """Recursively transform a node and its children."""
        if node is None:
            return None

        for hook in self._pre_hooks:
            node = hook(node)

        matching_rules = self._find_matching_rules(node)
        for rule in matching_rules:
            if rule.enabled:
                node = rule.apply(node)

        if hasattr(node, "children"):
            node.children = [self._transform_node(c) for c in node.children]

        for hook in self._post_hooks:
            node = hook(node)

        return node

    def _find_matching_rules(self, node: Any) -> list[TransformationRule]:
        """Find all rules that match the given node."""
        return [rule for rule in self._registry.get_all() if rule.enabled and rule.match(node)]

    def add_pre_hook(self, hook: callable) -> None:
        self._pre_hooks.append(hook)

    def add_post_hook(self, hook: callable) -> None:
        self._post_hooks.append(hook)


SQLSERVER_KEYWORDS = {
    "USER", "GROUP", "ORDER", "FULL", "CROSS", "NATURAL", "ROWS",
    "ROW", "CURRENT", "ACTION", "CHECK", "DEFAULT", "FOREIGN",
    "PRIMARY", "REFERENCES", "UNIQUE", "KEY", "VIEW", "READ",
    "WRITE", "ADMIN", "VALUE", "VALUES", "SEQUENCE", "OUTPUT",
    "LEVEL", "SOURCE", "TYPE", "STATISTICS", "WITH",
}


def register_default_rules(registry: RuleRegistry) -> None:
    """Register a comprehensive set of built-in transformation rules.

    Includes syntax, function, and data type rules that cover
    common SQL Server to PostgreSQL migration patterns.
    """
    # ── Syntax (pattern-based) rules ──────────────────────────────────────
    syntax_rules: list[TransformationRule] = [
        SyntaxRule(
            name="top_to_limit",
            category=RuleCategory.SYNTAX,
            pattern="top",
            description="SQL Server TOP N → PostgreSQL LIMIT N",
        ),
        SyntaxRule(
            name="identity_to_generated",
            category=RuleCategory.SYNTAX,
            pattern="identity",
            replacement_template="GENERATED BY DEFAULT AS IDENTITY",
            description="IDENTITY → GENERATED ... AS IDENTITY",
        ),
        SyntaxRule(
            name="output_to_returning",
            category=RuleCategory.SYNTAX,
            pattern="output",
            replacement_template="RETURNING",
            description="OUTPUT clause → RETURNING clause",
        ),
        SyntaxRule(
            name="print_to_raise_notice",
            category=RuleCategory.SYNTAX,
            pattern="print",
            replacement_template="RAISE NOTICE",
            description="PRINT → RAISE NOTICE",
        ),
        SyntaxRule(
            name="raiserror_to_raise",
            category=RuleCategory.SYNTAX,
            pattern="raiserror",
            replacement_template="RAISE",
            description="RAISERROR → RAISE",
        ),
        SyntaxRule(
            name="waitfor_to_pg_sleep",
            category=RuleCategory.SYNTAX,
            pattern="waitfor",
            replacement_template="pg_sleep",
            description="WAITFOR → pg_sleep()",
        ),
        SyntaxRule(
            name="cross_apply_to_lateral",
            category=RuleCategory.SYNTAX,
            pattern="cross_apply",
            replacement_template="CROSS JOIN LATERAL",
            description="CROSS APPLY → CROSS JOIN LATERAL",
        ),
        SyntaxRule(
            name="outer_apply_to_lateral",
            category=RuleCategory.SYNTAX,
            pattern="outer_apply",
            replacement_template="LEFT JOIN LATERAL",
            description="OUTER APPLY → LEFT JOIN LATERAL",
        ),
        SyntaxRule(
            name="with_ties_to_fetch",
            category=RuleCategory.SYNTAX,
            pattern="with_ties",
            replacement_template="WITH TIES (unsupported, use window function)",
            description="WITH TIES → requires window function rewrite",
        ),
        SyntaxRule(
            name="option_clause_to_comment",
            category=RuleCategory.SYNTAX,
            pattern="option",
            replacement_template="-- OPTION clause removed: not supported in PostgreSQL",
            description="OPTION clause → comment (not supported)",
        ),
    ]
    registry.register_many(syntax_rules)

    # ── Function mapping rules ────────────────────────────────────────────
    function_rules: list[TransformationRule] = [
        FunctionMappingRule(
            name="isnull_to_coalesce",
            category=RuleCategory.FUNCTION,
            source_function="ISNULL",
            target_function="COALESCE",
            description="ISNULL(a, b) → COALESCE(a, b)",
        ),
        FunctionMappingRule(
            name="getdate_to_now",
            category=RuleCategory.FUNCTION,
            source_function="GETDATE",
            target_function="CURRENT_TIMESTAMP",
            description="GETDATE() → CURRENT_TIMESTAMP",
        ),
        FunctionMappingRule(
            name="getutcdate_to_now_utc",
            category=RuleCategory.FUNCTION,
            source_function="GETUTCDATE",
            target_function="CURRENT_TIMESTAMP AT TIME ZONE 'UTC'",
            description="GETUTCDATE() → CURRENT_TIMESTAMP AT TIME ZONE 'UTC'",
        ),
        FunctionMappingRule(
            name="newid_to_gen_uuid",
            category=RuleCategory.FUNCTION,
            source_function="NEWID",
            target_function="gen_random_uuid",
            description="NEWID() → gen_random_uuid()",
        ),
        FunctionMappingRule(
            name="len_to_length",
            category=RuleCategory.FUNCTION,
            source_function="LEN",
            target_function="LENGTH",
            description="LEN(str) → LENGTH(str)",
        ),
        FunctionMappingRule(
            name="charindex_to_strpos",
            category=RuleCategory.FUNCTION,
            source_function="CHARINDEX",
            target_function="STRPOS",
            description="CHARINDEX(sub, str) → STRPOS(str, sub)",
        ),
        FunctionMappingRule(
            name="ceiling_to_ceil",
            category=RuleCategory.FUNCTION,
            source_function="CEILING",
            target_function="CEIL",
            description="CEILING(n) → CEIL(n)",
        ),
        FunctionMappingRule(
            name="user_name_to_current_user",
            category=RuleCategory.FUNCTION,
            source_function="USER_NAME",
            target_function="CURRENT_USER",
            description="USER_NAME() → CURRENT_USER",
        ),
        FunctionMappingRule(
            name="scope_identity_to_lastval",
            category=RuleCategory.FUNCTION,
            source_function="SCOPE_IDENTITY",
            target_function="LASTVAL",
            description="SCOPE_IDENTITY() → LASTVAL()",
        ),
        FunctionMappingRule(
            name="sysdatetime_to_now",
            category=RuleCategory.FUNCTION,
            source_function="SYSDATETIME",
            target_function="CURRENT_TIMESTAMP",
            description="SYSDATETIME() → CURRENT_TIMESTAMP",
        ),
        FunctionMappingRule(
            name="suser_sname_to_current_user",
            category=RuleCategory.FUNCTION,
            source_function="SUSER_SNAME",
            target_function="CURRENT_USER",
            description="SUSER_SNAME() → CURRENT_USER",
        ),
        FunctionMappingRule(
            name="space_to_repeat",
            category=RuleCategory.FUNCTION,
            source_function="SPACE",
            target_function="REPEAT",
            description="SPACE(n) → REPEAT(' ', n)",
        ),
        FunctionMappingRule(
            name="replicate_to_repeat",
            category=RuleCategory.FUNCTION,
            source_function="REPLICATE",
            target_function="REPEAT",
            description="REPLICATE(str, n) → REPEAT(str, n)",
        ),
        FunctionMappingRule(
            name="stuff_to_overlay",
            category=RuleCategory.FUNCTION,
            source_function="STUFF",
            target_function="OVERLAY",
            description="STUFF(str, start, len, new) → OVERLAY(str PLACING new FROM start FOR len)",
        ),
        FunctionMappingRule(
            name="patindex_to_position",
            category=RuleCategory.FUNCTION,
            source_function="PATINDEX",
            target_function="POSITION",
            description="PATINDEX(pattern, str) → POSITION(pattern IN str)",
        ),
        FunctionMappingRule(
            name="iif_to_case",
            category=RuleCategory.FUNCTION,
            source_function="IIF",
            target_function="CASE WHEN",
            description="IIF(cond, t, f) → CASE WHEN cond THEN t ELSE f END",
        ),
    ]
    registry.register_many(function_rules)

    # ── Data type mapping rules ───────────────────────────────────────────
    from domains.transpilation.type_mappings import DATA_TYPE_MAPPINGS
    registry.register_many(list(DATA_TYPE_MAPPINGS))
