"""
Module: domains/discovery/synonym_discovery.py
Purpose: Discovers SQL Server synonyms (CREATE SYNONYM) and surfaces them as migration
         blockers because PostgreSQL has no direct equivalent — callers must be rewritten
         to use views, foreign data wrappers, or direct table references.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


@dataclass
class SynonymInfo:
    schema_name: str
    synonym_name: str
    base_object_name: str
    is_cross_database: bool

    @property
    def migration_recommendation(self) -> str:
        if self.is_cross_database:
            return (
                f"Synonym '{self.schema_name}.{self.synonym_name}' → '{self.base_object_name}' "
                "references an object in another database. Replace with a PostgreSQL "
                "foreign data wrapper (postgres_fdw) or dblink view."
            )
        return (
            f"Synonym '{self.schema_name}.{self.synonym_name}' → '{self.base_object_name}'. "
            "Replace with a PostgreSQL VIEW or update callsites to reference the base table directly."
        )


class SynonymDiscovery:
    """Fix 5.3: discovers SQL Server synonyms per schema.

    Cross-database synonyms (base_object_name containing a server or database
    prefix, e.g. [OtherDB].[dbo].[tbl]) are flagged as requiring FDW rewrites.
    Same-database synonyms can be replaced by views or direct references.
    """

    _SQL = """
        SELECT
            s.name          AS schema_name,
            sy.name         AS synonym_name,
            sy.base_object_name
        FROM sys.synonyms   sy
        JOIN sys.schemas    s ON s.schema_id = sy.schema_id
        WHERE s.name = ?
        ORDER BY s.name, sy.name
    """

    async def discover(self, connector: Any, schema: str) -> list[SynonymInfo]:
        rows = await connector.execute(self._SQL, schema)
        result: list[SynonymInfo] = []
        for row in rows:
            base = row["base_object_name"] or ""
            # Cross-database refs have 3+ dot-separated parts: [db].[schema].[obj]
            parts = [p for p in base.split(".") if p]
            is_cross_db = len(parts) >= 3
            result.append(SynonymInfo(
                schema_name=row["schema_name"],
                synonym_name=row["synonym_name"],
                base_object_name=base,
                is_cross_database=is_cross_db,
            ))
        logger.info("synonym_discovery_complete", schema=schema, count=len(result))
        if result:
            logger.warning(
                "synonyms_require_manual_migration",
                schema=schema,
                count=len(result),
                cross_database=sum(1 for s in result if s.is_cross_database),
            )
        return result
