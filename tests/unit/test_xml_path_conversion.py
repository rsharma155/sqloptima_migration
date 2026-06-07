"""
Module: tests/unit/test_xml_path_conversion.py
Purpose: TDD tests for item 3.9 — FOR XML PATH / OPENXML conversion.
         Covers:
           - STUFF + FOR XML PATH → STRING_AGG
           - Bare FOR XML PATH → TODO comment
           - OPENXML → TODO comment
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import pytest

from domains.transpilation.converters.plpgsql._body_transforms import TsqlBodyConverter
from domains.transpilation.converters.plpgsql._xml_converter import _convert_for_xml_path


def _convert(sql: str) -> str:
    return TsqlBodyConverter.convert(sql, params=[])


# ---------------------------------------------------------------------------
# Direct helper tests
# ---------------------------------------------------------------------------

class TestForXmlPathDirect:
    """Unit tests for _convert_for_xml_path helper."""

    def test_stuff_for_xml_path_becomes_string_agg(self):
        sql = "STUFF((SELECT ', ' + name FROM tags FOR XML PATH('')), 1, 2, '')"
        result = _convert_for_xml_path(sql)
        assert "STRING_AGG" in result.upper(), (
            f"STUFF+FOR XML PATH should become STRING_AGG, got: {result!r}"
        )
        assert "FOR XML" not in result.upper() or "TODO" in result.upper(), (
            f"FOR XML PATH should be converted away: {result!r}"
        )

    def test_stuff_for_xml_path_preserves_separator(self):
        """The separator from STUFF(..., ', ' + col...) should be in STRING_AGG."""
        sql = "STUFF((SELECT ', ' + tag FROM items FOR XML PATH('')), 1, 2, '')"
        result = _convert_for_xml_path(sql)
        assert "', '" in result or ", " in result, (
            f"Separator should be preserved in STRING_AGG: {result!r}"
        )

    def test_stuff_for_xml_path_preserves_column(self):
        """The column being aggregated should appear in the STRING_AGG output."""
        sql = "STUFF((SELECT ',' + product_name FROM products FOR XML PATH('')), 1, 1, '')"
        result = _convert_for_xml_path(sql)
        assert "product_name" in result, (
            f"Column name should appear in STRING_AGG result: {result!r}"
        )

    def test_bare_for_xml_produces_todo(self):
        """Bare FOR XML PATH not in STUFF context should emit a TODO comment."""
        sql = "SELECT id, name FROM t FOR XML PATH('row')"
        result = _convert_for_xml_path(sql)
        assert "TODO" in result.upper(), (
            f"Bare FOR XML PATH should emit a TODO comment, got: {result!r}"
        )

    def test_openxml_produces_todo(self):
        """OPENXML(...) should be replaced with a TODO comment."""
        sql = "SELECT * FROM OPENXML(@hDoc, '/root/row', 2) WITH (id INT, name VARCHAR(100))"
        result = _convert_for_xml_path(sql)
        assert "TODO" in result.upper(), (
            f"OPENXML should emit a TODO comment, got: {result!r}"
        )
        assert "OPENXML" not in result.upper() or "TODO" in result.upper(), (
            f"OPENXML should be replaced: {result!r}"
        )

    def test_stuff_for_xml_from_table(self):
        """FROM clause table name should appear in STRING_AGG subquery."""
        sql = "STUFF((SELECT ';' + c.code FROM categories c FOR XML PATH('')), 1, 1, '')"
        result = _convert_for_xml_path(sql)
        assert "STRING_AGG" in result.upper()
        assert "categories" in result, (
            f"Source table should appear in output: {result!r}"
        )


# ---------------------------------------------------------------------------
# Integration via TsqlBodyConverter
# ---------------------------------------------------------------------------

class TestXmlPathViaConverter:
    """Integration: FOR XML PATH / OPENXML must be handled in the full converter pipeline."""

    def test_stuff_xml_converted_via_full_pipeline(self):
        sql = "SELECT STUFF((SELECT ', ' + name FROM t FOR XML PATH('')), 1, 2, '') AS names"
        result = _convert(sql)
        # Either converted to STRING_AGG or a TODO comment
        assert "STRING_AGG" in result.upper() or "TODO" in result.upper(), (
            f"STUFF+FOR XML PATH should be converted or have TODO: {result!r}"
        )

    def test_bare_for_xml_pipeline(self):
        sql = "SELECT col1 FROM t FOR XML PATH('')"
        result = _convert(sql)
        assert "TODO" in result.upper(), (
            f"Bare FOR XML PATH should produce TODO in pipeline: {result!r}"
        )

    def test_openxml_pipeline(self):
        sql = "INSERT INTO t SELECT * FROM OPENXML(@h, '/r', 2) WITH (id INT, v VARCHAR(10))"
        result = _convert(sql)
        assert "TODO" in result.upper(), (
            f"OPENXML should produce TODO in pipeline: {result!r}"
        )

    def test_comma_separator_stuff_xml(self):
        """Common pattern: comma-separated string from STUFF+FOR XML PATH."""
        sql = (
            "SELECT dept, "
            "STUFF((SELECT ',' + e.name FROM employees e WHERE e.dept_id = d.id "
            "FOR XML PATH('')), 1, 1, '') AS emp_names "
            "FROM departments d"
        )
        result = _convert(sql)
        # Should be converted to use STRING_AGG or have a TODO comment
        assert "STRING_AGG" in result.upper() or "TODO" in result.upper(), (
            f"Complex STUFF+FOR XML PATH should be handled: {result!r}"
        )
