"""
Module: domains/transpilation/schema_mapping_config.py
Purpose: Value-object that holds the source→target schema name mapping used
         during T-SQL → PL/pgSQL conversion.  A default mapping of
         ``dbo → public`` matches the most common SQL Server / PostgreSQL
         convention; callers may override per-project.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Default mapping covers the typical SQL Server → PostgreSQL migration path.
_DEFAULT_MAPPING: dict[str, str] = {"dbo": "public"}


@dataclass(frozen=True)
class SchemaMappingConfig:
    """Immutable map of SQL Server schema names to PostgreSQL schema names.

    Example::

        cfg = SchemaMappingConfig({"dbo": "public", "hr": "hr_schema"})
        cfg.map("dbo")       # → "public"
        cfg.map("hr")        # → "hr_schema"
        cfg.map("unknown")   # → "unknown"  (pass-through)
    """

    mapping: dict[str, str] = field(default_factory=lambda: dict(_DEFAULT_MAPPING))

    def map(self, source_schema: str) -> str:
        """Return the target schema name for *source_schema*.

        Falls back to *source_schema* unchanged if no mapping is defined.
        """
        return self.mapping.get(source_schema, source_schema)

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def default(cls) -> "SchemaMappingConfig":
        """Return a config with the ``dbo → public`` default."""
        return cls(mapping=dict(_DEFAULT_MAPPING))

    @classmethod
    def identity(cls) -> "SchemaMappingConfig":
        """Return a config that maps every schema to itself (no renaming)."""
        return cls(mapping={})

    @classmethod
    def from_dict(cls, mapping: dict[str, str]) -> "SchemaMappingConfig":
        """Build from an arbitrary source→target dict."""
        return cls(mapping=dict(mapping))
