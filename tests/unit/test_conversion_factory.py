"""Tests for shared ConversionService factory."""

from __future__ import annotations

from application.conversion_factory import build_conversion_service, build_schema_mapping
from application.conversion_service import ConversionService


def test_build_schema_mapping_dbo():
    assert build_schema_mapping("dbo", None) == {"dbo": "public"}


def test_build_conversion_service_returns_service():
    svc = build_conversion_service("dbo")
    assert isinstance(svc, ConversionService)
