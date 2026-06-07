"""
Module: application/discovery_service.py
Purpose: Application service that orchestrates schema discovery against a
         SQL Server or PostgreSQL source.  Decouples routers from the
         SqlServerMetadataDiscovery infrastructure class.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from typing import Any

from domains.discovery.discovery_engine import DiscoveryEngine, DiscoveryResult
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


class DiscoveryServiceError(Exception):
    pass


class DiscoveryService:
    """Thin orchestration layer over DiscoveryEngine.

    Routers call this service instead of instantiating infrastructure
    classes directly, keeping the DDD dependency rule intact.
    """

    async def discover(
        self,
        connector: Any,
        discovery_impl: Any,
        database: str,
        schema: str = "dbo",
    ) -> DiscoveryResult:
        """Run full discovery against *database* and return the result."""
        logger.info("discovery_start", database=database, schema=schema)
        engine = DiscoveryEngine(discovery_impl)
        result = await engine.discover_full(database, schemas=[schema])
        logger.info(
            "discovery_complete",
            database=database,
            schema=schema,
            total_objects=result.total_objects,
            total_tables=result.total_tables,
        )
        return result

    async def discover_cdc_status(
        self,
        discovery_impl: Any,
        database: str,
        schema: str,
    ) -> dict[str, Any]:
        """Return CDC enablement info (best-effort, empty dict on error)."""
        try:
            return await discovery_impl.discover_cdc_status(database, schema)
        except Exception as exc:
            logger.warning("cdc_status_failed", error=str(exc))
            return {"db_cdc_enabled": False, "tables": {}}

    async def discover_linked_server_refs(
        self, discovery_impl: Any, database: str
    ) -> list[dict[str, Any]]:
        """Return linked-server references (best-effort)."""
        try:
            return await discovery_impl.discover_linked_server_refs(database)
        except Exception as exc:
            logger.warning("linked_server_refs_failed", error=str(exc))
            return []
