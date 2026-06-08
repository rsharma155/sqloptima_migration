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
from domains.transpilation.schema_mapping_config import (
    DboSchemaStrategy,
    SchemaMappingConfig,
)


def build_schema_mapping(
    source_schema: str,
    target_schema: str | None = None,
    *,
    dbo_schema_strategy: DboSchemaStrategy | str | None = None,
) -> dict[str, str]:
    """Build source→target schema map for procedural conversion."""
    strategy = _normalize_dbo_strategy(dbo_schema_strategy)
    src = source_schema.strip()
    resolved = resolve_target_schema(source_schema, target_schema)

    if strategy == DboSchemaStrategy.PRESERVE_DBO and src.lower() == "dbo":
        return {}

    if src.lower() == resolved.lower():
        return {}

    if src.lower() == "dbo" and resolved.lower() == "dbo":
        return {}

    return {src: resolved}


def build_conversion_service(
    source_schema: str,
    target_schema: str | None = None,
    *,
    schema_mapping: dict[str, str] | None = None,
    dbo_schema_strategy: DboSchemaStrategy | str | None = None,
) -> ConversionService:
    """Construct ConversionService with the same mapping rules as conversion_router."""
    strategy = _normalize_dbo_strategy(dbo_schema_strategy)
    mapper: SchemaMapper | None = None

    if schema_mapping is not None:
        mapper = SchemaMapper(SchemaMappingConfig.from_dict(schema_mapping))
    else:
        explicit = build_schema_mapping(
            source_schema,
            target_schema,
            dbo_schema_strategy=strategy,
        )
        if explicit:
            mapper = SchemaMapper(SchemaMappingConfig.from_dict(explicit))
        elif strategy == DboSchemaStrategy.MAP_TO_PUBLIC and source_schema.lower() == "dbo":
            mapper = SchemaMapper(SchemaMappingConfig.default())
        else:
            mapper = SchemaMapper(SchemaMappingConfig.identity())

    return ConversionService(schema_mapper=mapper)


def _normalize_dbo_strategy(
    value: DboSchemaStrategy | str | None,
) -> DboSchemaStrategy:
    if value is None:
        return DboSchemaStrategy.MAP_TO_PUBLIC
    if isinstance(value, DboSchemaStrategy):
        return value
    normalized = str(value).strip().lower().replace("-", "_")
    if normalized in {"preserve", "preserve_dbo", "keep_dbo", "dbo"}:
        return DboSchemaStrategy.PRESERVE_DBO
    return DboSchemaStrategy.MAP_TO_PUBLIC
