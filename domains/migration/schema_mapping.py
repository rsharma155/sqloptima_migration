"""
Module: domains/migration/schema_mapping.py
Purpose: Fix F.3 — SchemaMapping lets operators rename schemas and tables during
         migration without modifying source SQL or target DDL.  Maps source
         (schema, table) pairs to target (schema, table) pairs at runtime.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ObjectRef:
    schema: str
    table: str

    def __str__(self) -> str:
        return f"{self.schema}.{self.table}"


class SchemaMapping:
    """Bidirectional name mapping between source and target schemas/tables.

    Fix F.3: supports the common scenario where the DBA wants to consolidate
    multiple SQL Server schemas into a single PostgreSQL schema, or rename
    tables during migration (e.g. UserProfile → user_profile).

    Usage::

        mapping = SchemaMapping()
        mapping.add("dbo", "UserProfile", "public", "user_profile")
        target_ref = mapping.resolve_target("dbo", "UserProfile")
        # → ObjectRef(schema="public", table="user_profile")
    """

    def __init__(self) -> None:
        self._map: dict[ObjectRef, ObjectRef] = {}
        self._schema_map: dict[str, str] = {}

    def add(
        self,
        source_schema: str,
        source_table: str,
        target_schema: str,
        target_table: str,
    ) -> None:
        """Add an explicit (schema, table) → (schema, table) mapping."""
        src = ObjectRef(schema=source_schema.lower(), table=source_table.lower())
        tgt = ObjectRef(schema=target_schema.lower(), table=target_table.lower())
        self._map[src] = tgt

    def add_schema_rename(self, source_schema: str, target_schema: str) -> None:
        """Map all tables in source_schema to target_schema (table names unchanged)."""
        self._schema_map[source_schema.lower()] = target_schema.lower()

    def resolve_target(self, source_schema: str, source_table: str) -> ObjectRef:
        """Return the target (schema, table) for the given source pair.

        Priority:
        1. Explicit table-level mapping.
        2. Schema-level rename (table name unchanged).
        3. Identity (no change).
        """
        src = ObjectRef(schema=source_schema.lower(), table=source_table.lower())
        if src in self._map:
            return self._map[src]
        if src.schema in self._schema_map:
            return ObjectRef(schema=self._schema_map[src.schema], table=src.table)
        return src

    def has_mapping(self, source_schema: str, source_table: str) -> bool:
        src = ObjectRef(schema=source_schema.lower(), table=source_table.lower())
        return src in self._map or src.schema in self._schema_map

    @classmethod
    def from_dict(cls, config: dict) -> "SchemaMapping":
        """Construct a SchemaMapping from a dict of the form::

            {
                "schema_renames": {"dbo": "public"},
                "table_mappings": {
                    "dbo.UserProfile": "public.user_profile",
                    "dbo.OrderLine": "public.order_item"
                }
            }
        """
        mapping = cls()
        for src_schema, tgt_schema in config.get("schema_renames", {}).items():
            mapping.add_schema_rename(src_schema, tgt_schema)
        for src_full, tgt_full in config.get("table_mappings", {}).items():
            src_parts = src_full.split(".", 1)
            tgt_parts = tgt_full.split(".", 1)
            if len(src_parts) == 2 and len(tgt_parts) == 2:
                mapping.add(src_parts[0], src_parts[1], tgt_parts[0], tgt_parts[1])
        return mapping
