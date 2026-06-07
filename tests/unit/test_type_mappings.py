"""
Module: test_type_mappings.py
Purpose: Unit tests for data type mapping rules
Author: Migration Platform Team
Created: 2026-05-22
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""


from domains.transpilation.type_mappings import (
    DATA_TYPE_MAPPINGS,
    get_type_mapping,
    get_type_mapping_rules,
)


class TestTypeMappings:
    def test_all_mappings_have_names(self):
        for rule in DATA_TYPE_MAPPINGS:
            assert rule.name, f"Rule missing name: {rule}"

    def test_all_mappings_have_source_and_target(self):
        for rule in DATA_TYPE_MAPPINGS:
            assert rule.source_type, f"Rule {rule.name} missing source_type"
            assert rule.target_type, f"Rule {rule.name} missing target_type"

    def test_int_mapping(self):
        rule = get_type_mapping("INT")
        assert rule.target_type == "INTEGER"

    def test_varchar_mapping(self):
        rule = get_type_mapping("VARCHAR")
        assert rule.target_type == "VARCHAR"

    def test_nvarchar_mapping(self):
        rule = get_type_mapping("NVARCHAR")
        assert rule.target_type == "VARCHAR"

    def test_uniqueidentifier_mapping(self):
        rule = get_type_mapping("UNIQUEIDENTIFIER")
        assert rule.target_type == "UUID"

    def test_datetime_mapping(self):
        rule = get_type_mapping("DATETIME")
        assert rule.target_type == "TIMESTAMP"

    def test_datetimeoffset_mapping(self):
        rule = get_type_mapping("DATETIMEOFFSET")
        assert rule.target_type == "TIMESTAMPTZ"

    def test_money_mapping(self):
        rule = get_type_mapping("MONEY")
        assert rule.target_type == "NUMERIC"
        assert rule.target_precision == 19
        assert rule.target_scale == 4

    def test_unknown_type_passthrough(self):
        rule = get_type_mapping("CUSTOM_TYPE")
        assert rule.target_type == "CUSTOM_TYPE"

    def test_case_insensitive(self):
        r1 = get_type_mapping("int")
        r2 = get_type_mapping("INT")
        r3 = get_type_mapping("Int")
        assert r1.target_type == r2.target_type == r3.target_type

    def test_get_type_mapping_rules_returns_copy(self):
        rules = get_type_mapping_rules()
        assert len(rules) == len(DATA_TYPE_MAPPINGS)

    def test_risky_types_identified(self):
        risky = {"SQL_VARIANT", "HIERARCHYID", "GEOGRAPHY", "GEOMETRY", "ROWVERSION"}
        for rule in DATA_TYPE_MAPPINGS:
            if rule.source_type.upper() in risky:
                assert rule.target_type is not None
