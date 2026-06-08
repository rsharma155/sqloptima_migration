"""
Module: discovery_engine.py
Purpose: Orchestrates full metadata discovery across SQL Server database
Author: Migration Platform Team
Created: 2026-05-22
Domain: Discovery
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""


from shared.contracts.base_connector import MetadataDiscoveryPort
from shared.kernel.database_object import (
    DatabaseObject,
    Table,
)
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


class DiscoveryResult:
    """Holds the results of a full discovery process."""

    def __init__(self):
        self.databases: list[DatabaseObject] = []
        self.schemas: dict[str, list[DatabaseObject]] = {}
        self.tables: dict[str, list[Table]] = {}
        self.views: dict[str, list[DatabaseObject]] = {}
        self.procedures: dict[str, list[DatabaseObject]] = {}
        self.functions: dict[str, list[DatabaseObject]] = {}
        self.triggers: dict[str, list[DatabaseObject]] = {}
        self.dependencies: list[dict] = []
        self.all_objects: list[DatabaseObject] = []

    @property
    def total_objects(self) -> int:
        return len(self.all_objects)

    @property
    def total_tables(self) -> int:
        return sum(len(tables) for tables in self.tables.values())


class DiscoveryEngine:
    """Orchestrates the full metadata discovery process.

    Coordinates discovery across all object types and builds a
    comprehensive model of the source database.
    """

    def __init__(self, metadata_discovery: MetadataDiscoveryPort):
        self._discovery = metadata_discovery

    async def discover_full(self, database: str, schemas: list[str] | None = None) -> DiscoveryResult:
        """Perform full discovery of a database.

        Args:
            database: The database name to discover.
            schemas: Optional list of schemas to discover. If None, discovers all.

        Returns:
            DiscoveryResult with all discovered objects.
        """
        result = DiscoveryResult()
        logger.debug("Starting discovery", database=database)

        target_schemas = schemas or []

        if not target_schemas:
            result.schemas[database] = await self._discovery.discover_schemas(database)
            target_schemas = [s.object_name for s in result.schemas[database]]
            logger.debug("Discovered schemas", database=database, count=len(target_schemas))

        for schema in target_schemas:
            logger.debug("Discovering schema", database=database, schema=schema)

            key = f"{database}.{schema}"

            tables = await self._discovery.discover_tables(database, schema)
            await self._attach_indexes_to_tables(database, schema, tables)
            result.tables[key] = tables
            result.all_objects.extend(tables)
            logger.debug("Discovered tables", schema=schema, count=len(tables))

            views = await self._discovery.discover_views(database, schema)
            result.views[key] = views
            result.all_objects.extend(views)
            logger.debug("Discovered views", schema=schema, count=len(views))

            procedures = await self._discovery.discover_procedures(database, schema)
            result.procedures[key] = procedures
            result.all_objects.extend(procedures)
            logger.debug("Discovered procedures", schema=schema, count=len(procedures))

            functions = await self._discovery.discover_functions(database, schema)
            result.functions[key] = functions
            result.all_objects.extend(functions)
            logger.debug("Discovered functions", schema=schema, count=len(functions))

        result.dependencies = await self._discovery.discover_dependencies(database)
        logger.debug(
            "Discovery completed",
            database=database,
            total_objects=result.total_objects,
            total_tables=result.total_tables,
        )

        return result

    async def _attach_indexes_to_tables(
        self, database: str, schema: str, tables: list[Table],
    ) -> None:
        """Attach per-table index metadata so schema comparison can diff indexes."""
        for table in tables:
            indexes = await self._discovery.discover_indexes(
                database, schema, table.object_name,
            )
            table.properties["indexes"] = indexes
            table.index_count = len(indexes)
