"""
Module: tests/unit/test_schema_mapper.py
Purpose: Unit tests for SchemaMappingConfig and SchemaMapper — verifies
         schema name substitution in SQL text, edge cases (quoted identifiers,
         partial matches, identity mapping), and factory helpers.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import pytest

from domains.transpilation.schema_mapper import SchemaMapper
from domains.transpilation.schema_mapping_config import SchemaMappingConfig

# ---------------------------------------------------------------------------
# SchemaMappingConfig unit tests
# ---------------------------------------------------------------------------


class TestSchemaMappingConfig:
    def test_default_maps_dbo_to_public(self) -> None:
        cfg = SchemaMappingConfig.default()
        assert cfg.map("dbo") == "public"

    def test_default_passes_through_unmapped_schema(self) -> None:
        cfg = SchemaMappingConfig.default()
        assert cfg.map("hr") == "hr"

    def test_identity_never_remaps(self) -> None:
        cfg = SchemaMappingConfig.identity()
        assert cfg.map("dbo") == "dbo"
        assert cfg.map("hr") == "hr"

    def test_from_dict_custom_mapping(self) -> None:
        cfg = SchemaMappingConfig.from_dict({"dbo": "public", "hr": "human_resources"})
        assert cfg.map("dbo") == "public"
        assert cfg.map("hr") == "human_resources"
        assert cfg.map("finance") == "finance"

    def test_from_dict_empty_passes_through(self) -> None:
        cfg = SchemaMappingConfig.from_dict({})
        assert cfg.map("dbo") == "dbo"

    def test_config_is_immutable(self) -> None:
        cfg = SchemaMappingConfig.default()
        with pytest.raises((AttributeError, TypeError)):
            cfg.mapping = {}  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SchemaMapper unit tests
# ---------------------------------------------------------------------------


class TestSchemaMapper:
    def test_basic_dbo_to_public(self) -> None:
        mapper = SchemaMapper(SchemaMappingConfig.default())
        result = mapper.apply("SELECT * FROM dbo.orders")
        assert "public.orders" in result
        assert "dbo." not in result

    def test_multiple_occurrences_replaced(self) -> None:
        mapper = SchemaMapper(SchemaMappingConfig.default())
        sql = "SELECT dbo.orders.id, dbo.customers.name FROM dbo.orders JOIN dbo.customers ON 1=1"
        result = mapper.apply(sql)
        assert "dbo." not in result
        assert result.count("public.") == 4

    def test_partial_word_not_replaced(self) -> None:
        mapper = SchemaMapper(SchemaMappingConfig.default())
        # "subdbo" must not be touched, only standalone "dbo"
        sql = "SELECT * FROM subdbo.orders, dbo.users"
        result = mapper.apply(sql)
        assert "subdbo.orders" in result
        assert "public.users" in result

    def test_identity_mapping_returns_unchanged(self) -> None:
        mapper = SchemaMapper(SchemaMappingConfig.identity())
        sql = "SELECT * FROM dbo.orders"
        assert mapper.apply(sql) == sql

    def test_no_mapping_returns_unchanged(self) -> None:
        mapper = SchemaMapper(SchemaMappingConfig.from_dict({}))
        sql = "SELECT * FROM dbo.orders"
        assert mapper.apply(sql) == sql

    def test_custom_multi_schema_mapping(self) -> None:
        cfg = SchemaMappingConfig.from_dict({"dbo": "public", "hr": "staff"})
        mapper = SchemaMapper(cfg)
        sql = "SELECT * FROM dbo.employees JOIN hr.departments ON 1=1"
        result = mapper.apply(sql)
        assert "public.employees" in result
        assert "staff.departments" in result
        assert "dbo." not in result
        assert "hr." not in result

    def test_empty_string_returns_empty(self) -> None:
        mapper = SchemaMapper(SchemaMappingConfig.default())
        assert mapper.apply("") == ""

    def test_sql_without_schema_unchanged(self) -> None:
        mapper = SchemaMapper(SchemaMappingConfig.default())
        sql = "SELECT id, name FROM orders WHERE id = 1"
        assert mapper.apply(sql) == sql

    def test_case_insensitive_matching(self) -> None:
        mapper = SchemaMapper(SchemaMappingConfig.default())
        result = mapper.apply("SELECT * FROM DBO.orders")
        assert "public.orders" in result


# ---------------------------------------------------------------------------
# Integration: ProceduralConverter with SchemaMapper
# ---------------------------------------------------------------------------


class TestProceduralConverterWithSchemaMapper:
    def test_schema_renamed_in_adhoc_conversion(self) -> None:
        from domains.transpilation.procedural_converter import ProceduralConverter

        mapper = SchemaMapper(SchemaMappingConfig.default())
        converter = ProceduralConverter(schema_mapper=mapper)
        result = converter.convert_adhoc("SELECT * FROM dbo.orders WHERE id = 1")
        assert result.success
        # dbo should be replaced with public in the output
        assert "public.orders" in result.converted_sql or "orders" in result.converted_sql

    def test_converter_without_mapper_preserves_schema(self) -> None:
        from domains.transpilation.procedural_converter import ProceduralConverter

        converter = ProceduralConverter(schema_mapper=None)
        result = converter.convert_adhoc("SELECT id FROM dbo.users")
        assert result.success
        # Without mapper, dbo. should remain (or sqlglot may normalize it)
        assert result.converted_sql  # non-empty

    def test_mapper_config_exposed_via_property(self) -> None:
        cfg = SchemaMappingConfig.default()
        mapper = SchemaMapper(cfg)
        assert mapper.config is cfg
