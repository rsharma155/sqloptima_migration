"""
Module: target_schema_resolver.py
Purpose: Resolve PostgreSQL target schema from SQL Server source schema during migration.
         Preserves source schema names (e.g. Sales, Person) so stored procedures and
         cross-schema references remain valid after migration. Only ``dbo`` maps to
         ``public`` by default.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from domains.transpilation.schema_mapping_config import SchemaMappingConfig


def resolve_target_schema(
    source_schema: str,
    target_schema: str | None = None,
) -> str:
    """Return the PostgreSQL schema for tables migrated from *source_schema*.

    When *target_schema* is omitted or blank, apply the default mapping
    (``dbo`` → ``public``; all other source schemas keep the same name).

    When *target_schema* is ``public`` but *source_schema* is not ``dbo``, treat
    ``public`` as the legacy unset default (API/UI used to default every job to
    public). This keeps multi-schema databases like AdventureWorks aligned so
    schema-qualified stored procedures resolve after migration.
    """
    src = str(source_schema).strip()
    if target_schema is None or not str(target_schema).strip():
        return SchemaMappingConfig.default().map(src)

    tgt = str(target_schema).strip()
    if tgt.lower() == "public" and src.lower() != "dbo":
        return SchemaMappingConfig.default().map(src)
    return tgt
