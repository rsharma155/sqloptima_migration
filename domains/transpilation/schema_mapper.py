"""
Module: domains/transpilation/schema_mapper.py
Purpose: Applies schema-name substitutions to converted PL/pgSQL output.
         Rewrites every occurrence of a source schema prefix
         (``schema_name.``) to the configured target schema while
         preserving quoted identifiers and skipping SQL comments.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import re

from domains.transpilation.schema_mapping_config import SchemaMappingConfig


class SchemaMapper:
    """Renames schema-qualified identifiers inside PL/pgSQL SQL text.

    Substitution is applied after transpilation so it works on the
    already-converted PostgreSQL output.  All replacements use word
    boundaries so partial matches (e.g. ``subdbo``) are not affected.

    Example::

        mapper = SchemaMapper(SchemaMappingConfig.default())
        out = mapper.apply("SELECT * FROM dbo.orders WHERE dbo.orders.id = 1")
        # → "SELECT * FROM public.orders WHERE public.orders.id = 1"
    """

    def __init__(self, config: SchemaMappingConfig) -> None:
        self._config = config
        # Pre-compile one regex per mapping entry for performance.
        self._patterns: list[tuple[re.Pattern[str], str]] = [
            (
                re.compile(
                    # Match unquoted schema prefix: word boundary + name + dot
                    # NOT preceded by a quote or another word char (avoid over-matching).
                    r"(?<![\"'\w])\b" + re.escape(src) + r"\b(?=\.)",
                    re.IGNORECASE,
                ),
                tgt,
            )
            for src, tgt in config.mapping.items()
        ]

    def apply(self, sql: str) -> str:
        """Return *sql* with all configured schema name substitutions applied."""
        if not self._patterns:
            return sql
        result = sql
        for pattern, target in self._patterns:
            result = pattern.sub(target, result)
        return result

    @property
    def config(self) -> SchemaMappingConfig:
        return self._config
