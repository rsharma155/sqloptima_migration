"""
Module: test_transformation_rule.py
Purpose: Unit tests for transformation rule engine
Author: Migration Platform Team
Created: 2026-05-22
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""


from sqlglot import exp, parse_one

from domains.transpilation.ir_models import DataTypeNode, IrNode, IrNodeType
from domains.transpilation.transformation_rule import (
    DataTypeMappingRule,
    FunctionMappingRule,
    RuleRegistry,
    SyntaxRule,
    TransformationEngine,
)


class TestRuleRegistry:
    def test_register_and_get_rules(self):
        registry = RuleRegistry()
        rule = SyntaxRule(name="test_rule", category="syntax", pattern="select")
        registry.register(rule)
        assert registry.count == 1
        assert len(registry.get_all()) == 1

    def test_get_by_category(self):
        registry = RuleRegistry()
        r1 = SyntaxRule(name="r1", category="syntax", pattern="p1")
        r2 = DataTypeMappingRule(name="r2", category="datatype", source_type="INT", target_type="INTEGER")
        registry.register_many([r1, r2])
        syntax_rules = registry.get_by_category("syntax")
        assert len(syntax_rules) == 1
        assert syntax_rules[0].name == "r1"

    def test_get_by_name(self):
        registry = RuleRegistry()
        rule = SyntaxRule(name="unique_rule", category="syntax", pattern="select")
        registry.register(rule)
        found = registry.get_by_name("unique_rule")
        assert found is not None
        assert found.name == "unique_rule"

    def test_remove_rule(self):
        registry = RuleRegistry()
        rule = SyntaxRule(name="remove_me", category="syntax", pattern="test")
        registry.register(rule)
        registry.remove(rule.rule_id)
        assert registry.count == 0

    def test_clear(self):
        registry = RuleRegistry()
        registry.register(SyntaxRule(name="a", category="syntax", pattern="p"))
        registry.register(SyntaxRule(name="b", category="syntax", pattern="p"))
        registry.clear()
        assert registry.count == 0


class TestFunctionMappingRule:
    def test_match_function_by_name(self):
        rule = FunctionMappingRule(
            name="db_name_to_current_database",
            category="function",
            source_function="DB_NAME",
            target_function="CURRENT_DATABASE",
        )
        ast = parse_one("SELECT DB_NAME()", read="tsql")
        select = ast.find(exp.Func)
        assert select is not None
        assert select.name.upper() == "DB_NAME"
        assert rule.match(select)

    def test_no_match_different_function(self):
        rule = FunctionMappingRule(
            name="db_name_to_current_database",
            category="function",
            source_function="DB_NAME",
            target_function="CURRENT_DATABASE",
        )
        ast = parse_one("SELECT HOST_NAME()", read="tsql")
        func = ast.find(exp.Func)
        if func:
            assert not rule.match(func)


class TestDataTypeMappingRule:
    def test_match_int(self):
        rule = DataTypeMappingRule(
            name="int_to_integer",
            category="datatype",
            source_type="INT",
            target_type="INTEGER",
        )
        node = DataTypeNode(type_name="INT")
        assert rule.match(node)

    def test_no_match_different_type(self):
        rule = DataTypeMappingRule(
            name="int_to_integer",
            category="datatype",
            source_type="INT",
            target_type="INTEGER",
        )
        node = DataTypeNode(type_name="VARCHAR")
        assert not rule.match(node)

    def test_apply_int_to_integer(self):
        rule = DataTypeMappingRule(
            name="int_to_integer",
            category="datatype",
            source_type="INT",
            target_type="INTEGER",
        )
        node = DataTypeNode(type_name="INT", is_nullable=False)
        result = rule.apply(node)
        assert result.type_name == "INTEGER"
        assert result.is_nullable is False


class TestTransformationEngine:
    def test_engine_creation(self):
        engine = TransformationEngine()
        assert engine.registry.count == 0

    def test_engine_with_registry(self):
        registry = RuleRegistry()
        engine = TransformationEngine(registry)
        assert engine.registry is registry

    def test_engine_transforms_types(self):
        registry = RuleRegistry()
        rule = DataTypeMappingRule(
            name="int_to_integer",
            category="datatype",
            source_type="INT",
            target_type="INTEGER",
        )
        registry.register(rule)
        engine = TransformationEngine(registry)

        from domains.transpilation.ir_models import IrProgram
        program = IrProgram()
        type_node = DataTypeNode(type_name="INT")
        col_node = IrNode(node_type=IrNodeType.COLUMN_DEF, children=[type_node])
        program.statements.append(col_node)

        result = engine.transform(program)
        assert len(result.statements) > 0
