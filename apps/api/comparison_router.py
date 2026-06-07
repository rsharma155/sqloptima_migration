"""
Module: comparison_router.py
Purpose: FastAPI REST API layer
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from domains.comparison.comparison_engine import (
    ComparisonEngine,
    MatchStatus,
)
from domains.comparison.object_comparator import ObjectComparator
from shared.errors.error_catalog import format_connection_error
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/comparison", tags=["comparison"])

_comparison_store: dict[UUID, ComparisonResultResponse] = {}


class CompareRequest(BaseModel):
    source_connection_id: UUID
    target_connection_id: UUID
    source_schema: str = "dbo"
    target_schema: str = "public"


class CompareTableRequest(BaseModel):
    source_connection_id: UUID
    target_connection_id: UUID
    schema_name: str
    table_name: str


class ComparisonResponse(BaseModel):
    comparison_id: UUID
    summary: dict
    tree: list[dict]
    source_tree: list[dict]
    target_tree: list[dict]
    duration_ms: float


class DiffEntryResponse(BaseModel):
    property: str
    source: str | None
    target: str | None
    severity: str


class ObjectDetailResponse(BaseModel):
    path: str
    source_name: str | None = None
    target_name: str | None = None
    status: MatchStatus
    differences: list[DiffEntryResponse] = []


class ComparisonResultResponse:
    def __init__(self, comparison_id: UUID, response: ComparisonResponse):
        self.comparison_id = comparison_id
        self.response = response
        self.details: dict[str, ObjectDetailResponse] = {}


def _serialize_tree(nodes: list) -> list[dict]:
    result = []
    for node in nodes:
        entry = {
            "name": node.name,
            "node_type": node.node_type,
            "status": node.status.value if isinstance(node.status, MatchStatus) else node.status,
            "children": _serialize_tree(node.children),
            "properties": node.properties,
        }
        result.append(entry)
    return result


def _lookup_connection(connection_id: UUID) -> dict:
    """Look up a connection from the shared store, raise 422 if not found."""
    from apps.api.connection_store import get_entry
    entry = get_entry(str(connection_id))
    if not entry:
        raise HTTPException(
            status_code=422,
            detail=f"Connection {connection_id} not found. Add a connection in Settings first.",
        )
    return entry


@router.post("/compare", response_model=ComparisonResponse)
async def compare_databases(req: CompareRequest):
    engine = ComparisonEngine(ObjectComparator())

    comparison_id = uuid4()

    from apps.api.connection_store import get_decrypted_password
    from domains.discovery.discovery_engine import DiscoveryEngine
    from infrastructure.postgres.postgres_connector import (
        PostgresConnectionConfig,
        PostgresConnector,
    )
    from infrastructure.postgres.postgres_discovery import PostgresMetadataDiscovery
    from infrastructure.sqlserver.sqlserver_connector import (
        SqlServerConnector,
        sqlserver_config_from_entry,
    )
    from infrastructure.sqlserver.sqlserver_discovery import SqlServerMetadataDiscovery

    src_entry = _lookup_connection(req.source_connection_id)
    tgt_entry = _lookup_connection(req.target_connection_id)

    src_password = get_decrypted_password(src_entry)
    tgt_password = get_decrypted_password(tgt_entry)

    source_config = sqlserver_config_from_entry(src_entry, password=src_password)
    target_config = PostgresConnectionConfig(
        host=tgt_entry["host"],
        port=int(tgt_entry.get("port", 5432)),
        database=tgt_entry["database"],
        username=tgt_entry.get("username", ""),
        password=tgt_password,
    )

    source_connector = SqlServerConnector(source_config)
    target_connector = PostgresConnector(target_config)

    try:
        await source_connector.connect()
    except Exception as exc:
        logger.error("Failed to connect to source for comparison", error=str(exc))
        raise HTTPException(
            status_code=502,
            detail=format_connection_error(str(exc), conn_type="source"),
        ) from None

    try:
        await target_connector.connect()
    except Exception as exc:
        await source_connector.disconnect()
        logger.error("Failed to connect to target for comparison", error=str(exc))
        raise HTTPException(
            status_code=502,
            detail=format_connection_error(str(exc), conn_type="target"),
        ) from None

    source_discovery = SqlServerMetadataDiscovery(source_connector)
    target_discovery = PostgresMetadataDiscovery(target_connector)

    source_engine = DiscoveryEngine(source_discovery)
    target_engine = DiscoveryEngine(target_discovery)

    try:
        logger.info("Discovering source database", schema=req.source_schema)
        source_result = await source_engine.discover_full(source_config.database, schemas=[req.source_schema])
        logger.info("Discovering target database", schema=req.target_schema)
        target_result = await target_engine.discover_full(target_config.database, schemas=[req.target_schema])
    except Exception as exc:
        logger.error("Failed to discover database objects for comparison", error=str(exc))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to discover database objects: {exc}",
        ) from None

    result = engine.compare_databases(
        source_result,
        target_result,
        source_schema=req.source_schema,
        target_schema=req.target_schema,
        source_database=source_config.database,
        target_database=target_config.database,
    )
    logger.info(
        "Comparison completed",
        comparison_id=str(comparison_id),
        matched=result.matched,
        source_only=result.source_only,
        target_only=result.target_only,
        duration_ms=result.duration_ms,
    )

    await source_connector.disconnect()
    await target_connector.disconnect()

    serialized_tree = _serialize_tree(result.tree)
    serialized_source_tree = _serialize_tree(result.source_tree)
    serialized_target_tree = _serialize_tree(result.target_tree)

    summary = {
        "total_source_objects": result.total_source_objects,
        "total_target_objects": result.total_target_objects,
        "matched": result.matched,
        "source_only": result.source_only,
        "target_only": result.target_only,
        "partial_match": result.partial_match,
        "source_database": result.source_database if result.source_database != "unknown" else source_config.database,
        "target_database": result.target_database if result.target_database != "unknown" else target_config.database,
        "source_schema": req.source_schema,
        "target_schema": req.target_schema,
    }

    response = ComparisonResponse(
        comparison_id=comparison_id,
        summary=summary,
        tree=serialized_tree,
        source_tree=serialized_source_tree,
        target_tree=serialized_target_tree,
        duration_ms=result.duration_ms,
    )

    stored = ComparisonResultResponse(comparison_id=comparison_id, response=response)

    for match in (engine.compare_tables(source_result.tables, target_result.tables)
                  + engine.compare_procedures(source_result.procedures, target_result.procedures)
                  + engine.compare_functions(source_result.functions, target_result.functions)):
        obj = match.source_object or match.target_object
        if obj:
            path = obj.fully_qualified_name
            stored.details[path] = ObjectDetailResponse(
                path=path,
                source_name=match.source_object.object_name if match.source_object else None,
                target_name=match.target_object.object_name if match.target_object else None,
                status=match.match_status,
                differences=[
                    DiffEntryResponse(
                        property=d.property_name,
                        source=str(d.source_value) if d.source_value is not None else None,
                        target=str(d.target_value) if d.target_value is not None else None,
                        severity=d.severity,
                    )
                    for d in match.differences
                ],
            )

    _comparison_store[comparison_id] = stored
    return response


@router.get("/compare/{comparison_id}/tree")
async def get_comparison_tree(comparison_id: UUID):
    stored = _comparison_store.get(comparison_id)
    if not stored:
        logger.warning("Comparison not found for tree request", comparison_id=str(comparison_id))
        raise HTTPException(status_code=404, detail="Comparison not found")
    return stored.response.tree


@router.get("/compare/{comparison_id}/object/{path:path}")
async def get_object_detail(comparison_id: UUID, path: str):
    stored = _comparison_store.get(comparison_id)
    if not stored:
        logger.warning("Comparison not found for object detail", comparison_id=str(comparison_id))
        raise HTTPException(status_code=404, detail="Comparison not found")
    detail = stored.details.get(path)
    if not detail:
        logger.warning("Object not found in comparison", comparison_id=str(comparison_id), path=path)
        raise HTTPException(status_code=404, detail=f"Object not found: {path}")
    return detail
