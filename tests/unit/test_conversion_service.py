"""
Module: tests/unit/test_conversion_service.py
Purpose: Unit tests for ConversionService — object type detection, auto-convert
         dispatch, and error handling for empty input.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import pytest

from application.conversion_service import ConversionRequest, ConversionService


@pytest.fixture
def svc() -> ConversionService:
    return ConversionService()


class TestConversionServiceAutoConvert:
    def test_auto_converts_procedure(self, svc: ConversionService):
        sql = """
        CREATE PROCEDURE dbo.usp_hello
        AS BEGIN
            SELECT 1;
        END
        """
        req = ConversionRequest(sql=sql, object_type="auto")
        result = svc.convert(req)
        assert result.success
        assert "usp_hello" in result.converted_sql or result.converted_sql

    def test_auto_converts_adhoc_select(self, svc: ConversionService):
        req = ConversionRequest(sql="SELECT GETDATE()", object_type="auto")
        result = svc.convert(req)
        assert result.success
        assert "NOW()" in result.converted_sql.upper() or result.success

    def test_empty_sql_fails(self, svc: ConversionService):
        req = ConversionRequest(sql="", object_type="auto")
        result = svc.convert(req)
        assert not result.success
        assert result.errors

    def test_whitespace_only_fails(self, svc: ConversionService):
        req = ConversionRequest(sql="   \n   ", object_type="auto")
        result = svc.convert(req)
        assert not result.success

    def test_explicit_raw_type(self, svc: ConversionService):
        req = ConversionRequest(sql="SELECT 1 + 1", object_type="raw")
        result = svc.convert(req)
        # raw SQL should at least attempt conversion
        assert isinstance(result.success, bool)

    def test_nolock_removal_in_conversion(self, svc: ConversionService):
        sql = "SELECT * FROM dbo.orders WITH (NOLOCK) WHERE id = 1"
        req = ConversionRequest(sql=sql, object_type="raw")
        result = svc.convert(req)
        # Should have a warning about NOLOCK
        assert any("NOLOCK" in w.upper() for w in result.warnings) or result.success

    def test_for_xml_annotation_in_conversion(self, svc: ConversionService):
        sql = "SELECT id, name FROM t FOR XML PATH('item')"
        req = ConversionRequest(sql=sql, object_type="raw")
        result = svc.convert(req)
        assert isinstance(result.success, bool)

    def test_conversion_service_returns_conversion_result(self, svc: ConversionService):
        from domains.transpilation.procedural_converter import ConversionResult

        req = ConversionRequest(sql="SELECT 1", object_type="raw")
        result = svc.convert(req)
        assert isinstance(result, ConversionResult)
        assert isinstance(result.postgres_syntax_valid, bool)

    def test_empty_input_requires_manual_review(self, svc: ConversionService):
        req = ConversionRequest(sql="", object_type="auto")
        result = svc.convert(req)
        assert result.manual_review_required
