"""
Module: conversion_factory.py
Purpose: Shared factory for ConversionService — same schema-mapping rules as /convert API.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from application.conversion_service import ConversionService
from domains.migration.target_schema_resolver import resolve_target_schema
from domains.transpilation.schema_mapper import SchemaMapper
from domains.transpilation.schema_mapping_config import SchemaMappingConfig


def build_schema_mapping(source_schema: str, target_schema: str | None) -> dict[str, str]:
    """Build source→target schema map for procedural conversion."""
    resolved = resolve_target_schema(source_schema, target_schema)
    src = source_schema.strip()
    if src.lower() == resolved.lower():
        return {}
    return {src: resolved}


def build_conversion_service(
    source_schema: str,
    target_schema: str | None = None,
    *,
    schema_mapping: dict[str, str] | None = None,
) -> ConversionService:
    """Construct ConversionService with the same mapping rules as conversion_router."""
    mapper: SchemaMapper | None = None
    if schema_mapping is not None:
        mapper = SchemaMapper(SchemaMappingConfig.from_dict(schema_mapping))
    else:
        explicit = build_schema_mapping(source_schema, target_schema)
        if explicit:
            mapper = SchemaMapper(SchemaMappingConfig.from_dict(explicit))
        elif source_schema.lower() != "public":
            mapper = SchemaMapper(SchemaMappingConfig.default())
    return ConversionService(schema_mapper=mapper)
