# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""Connection management routes.

Operator: GET/POST/PUT /connections, POST /connections/{id}/test, POST /connections/test-raw
Admin:    DELETE /connections/{id}, POST /create-database
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from application.migration_service import make_connector
from apps.api.connection_store import (
    delete_connection_async,
    get_all,
    get_decrypted_password,
    get_entry,
    save_connection_async,
    set_entry,
    update_test_status_async,
)
from apps.api.middleware.auth import UserRole, require_role
from shared.errors.error_catalog import humanize_connection_message
from shared.logging.structured_logging import get_logger
from shared.tenancy.project_scope import resolve_project_filter

logger = get_logger(__name__)

router = APIRouter(tags=["connections"])

_DB_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")


def _normalize_name(name: str) -> str:
    return name.strip().lower()


def _find_duplicate_name(name: str, exclude_id: str | None = None) -> dict | None:
    normalized = _normalize_name(name)
    if not normalized:
        return None
    for cid, conn in get_all(None).items():
        if exclude_id and cid == exclude_id:
            continue
        if _normalize_name(conn.get("name", "")) == normalized:
            return conn
    return None


# ---- Models ----

class ConnectionCreateRequest(BaseModel):
    name: str
    type: str
    host: str
    port: int
    database: str
    username: str
    password: str
    trust_server_certificate: bool = False
    project_id: str | None = None


class ConnectionResponse(BaseModel):
    id: str
    name: str
    type: str
    host: str
    port: int
    database: str
    username: str
    trust_server_certificate: bool = False
    project_id: str | None = None
    status: str = "disconnected"
    created_at: str = ""


class TestRawConnectionRequest(BaseModel):
    type: str
    host: str
    port: int
    database: str
    username: str
    password: str = ""
    trust_server_certificate: bool = False


class CreateDatabaseRequest(BaseModel):
    connection_id: UUID
    database_name: str


class CreateDatabaseResponse(BaseModel):
    success: bool
    message: str
    database: str


class PrivilegeScriptResponse(BaseModel):
    engine: str
    title: str
    recommended_login: str | None = None
    recommended_role: str | None = None
    default_schema: str | None = None
    privileges: list[str]
    capabilities: list[str]
    not_granted: list[str]
    file: str
    purpose: str
    variables: dict[str, str]
    run_example: str
    content: str


class PrivilegeScriptBundleResponse(BaseModel):
    source: PrivilegeScriptResponse
    target: PrivilegeScriptResponse


# ---- Endpoints ----

@router.get("/connections/privilege-scripts", response_model=PrivilegeScriptBundleResponse)
async def get_connection_privilege_scripts(_: dict = require_role(UserRole.VIEWER)):
    """Return least-privilege bootstrap SQL for source (SQL Server) and target (PostgreSQL)."""
    from infrastructure.sql_scripts.script_catalog import get_privilege_script_bundle

    return get_privilege_script_bundle()

@router.get("/connections", response_model=list[ConnectionResponse])
async def list_connections(
    project_id: str | None = Query(default=None),
    user: dict = require_role(UserRole.VIEWER),
):
    scope = resolve_project_filter(
        project_id,
        user_project_id=user.get("project_id"),
        is_admin=user.get("role") == UserRole.ADMIN.value,
    )
    return [
        ConnectionResponse(id=cid, **{k: v for k, v in conn.items() if k != "password"})
        for cid, conn in get_all(scope).items()
    ]


@router.post("/connections", response_model=ConnectionResponse)
async def create_connection(req: ConnectionCreateRequest, user: dict = require_role(UserRole.OPERATOR)):
    from apps.api.dependencies import get_secrets
    if _find_duplicate_name(req.name):
        raise HTTPException(
            status_code=409,
            detail=f"A connection named '{req.name.strip()}' already exists",
        )
    cid = str(uuid4())
    entry = req.model_dump()
    if not entry.get("project_id") and user.get("project_id"):
        entry["project_id"] = user["project_id"]
    secrets = get_secrets()
    if secrets and entry.get("password"):
        entry["password"] = secrets.encrypt(entry["password"])
    entry["created_at"] = datetime.now(UTC).isoformat()
    entry["status"] = "disconnected"
    set_entry(cid, entry)
    await save_connection_async(cid)
    return ConnectionResponse(id=cid, **entry)


@router.put("/connections/{connection_id}", response_model=ConnectionResponse)
async def update_connection(connection_id: str, req: ConnectionCreateRequest, _: dict = require_role(UserRole.OPERATOR)):
    from apps.api.dependencies import get_secrets
    existing = get_entry(connection_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Connection not found")
    if _find_duplicate_name(req.name, exclude_id=connection_id):
        raise HTTPException(
            status_code=409,
            detail=f"A connection named '{req.name.strip()}' already exists",
        )
    entry = req.model_dump()
    secrets = get_secrets()
    if secrets and entry.get("password"):
        entry["password"] = secrets.encrypt(entry["password"])
    elif not entry.get("password"):
        entry["password"] = existing.get("password", "")
    entry["created_at"] = existing.get("created_at", datetime.now(UTC).isoformat())
    entry["status"] = existing.get("status", "disconnected")
    set_entry(connection_id, entry)
    await save_connection_async(connection_id)
    return ConnectionResponse(id=connection_id, **entry)


@router.delete("/connections/{connection_id}")
async def delete_connection(connection_id: str, _: dict = require_role(UserRole.OPERATOR)):
    if get_entry(connection_id):
        await delete_connection_async(connection_id)
        return {"message": "Connection deleted"}

    from infrastructure.metadata_db.repositories import ConnectionRepository
    from infrastructure.metadata_db.session import AsyncSessionFactory

    async with AsyncSessionFactory() as session:
        repo = ConnectionRepository(session)
        record = await repo.get_by_id(connection_id)
        if not record:
            raise HTTPException(status_code=404, detail="Connection not found")
        await repo.delete(connection_id)
        await session.commit()

    remove_entry(connection_id)
    return {"message": "Connection deleted"}


@router.post("/connections/{connection_id}/test")
async def test_connection(connection_id: str, _: dict = require_role(UserRole.OPERATOR)):
    conn = get_entry(connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        connector, _ = await make_connector(conn)
        await connector.connect()
        await connector.disconnect()
        await update_test_status_async(connection_id, ok=True)
        return {"status": "connected", "message": "Connection successful"}
    except Exception as e:
        logger.error("Connection test failed", connection_id=connection_id, error=str(e))
        await update_test_status_async(connection_id, ok=False)
        return {
            "status": "error",
            "message": humanize_connection_message(
                str(e),
                conn_type=conn.get("type", "source"),
                host=conn.get("host"),
                port=int(conn.get("port", 1433 if conn.get("type") == "source" else 5432)),
            ),
        }


@router.post("/connections/test-raw")
async def test_raw_connection(req: TestRawConnectionRequest, _: dict = require_role(UserRole.OPERATOR)):
    try:
        if req.type == "source":
            from infrastructure.sqlserver.sqlserver_connector import SqlServerConnectionConfig, SqlServerConnector
            connector = SqlServerConnector(SqlServerConnectionConfig(
                host=req.host, port=req.port, database=req.database,
                username=req.username, password=req.password,
                trust_server_certificate=req.trust_server_certificate,
            ))
        else:
            from infrastructure.postgres.postgres_connector import (
                PostgresConnector,
                postgres_config_from_entry,
            )
            connector = PostgresConnector(postgres_config_from_entry(
                {
                    "host": req.host,
                    "port": req.port,
                    "database": req.database,
                    "username": req.username,
                },
                password=req.password,
            ))
        await connector.connect()
        await connector.disconnect()
        return {"status": "connected", "message": "Connection successful"}
    except Exception as e:
        logger.error("Raw connection test failed", error=str(e))
        return {
            "status": "error",
            "message": humanize_connection_message(
                str(e),
                conn_type=req.type,
                host=req.host,
                port=req.port,
            ),
        }


@router.post("/create-database", response_model=CreateDatabaseResponse)
async def create_target_database(req: CreateDatabaseRequest, _: dict = require_role(UserRole.ADMIN)):
    # Validate before any I/O so injection strings are rejected immediately.
    if not _DB_NAME_RE.match(req.database_name):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid database name '{req.database_name}'. Must match [a-zA-Z_][a-zA-Z0-9_]{{0,62}}",
        )
    import asyncpg  # deferred — only needed when name is valid and connection exists
    entry = get_entry(str(req.connection_id))
    if not entry:
        raise HTTPException(status_code=404, detail="Connection not found")
    password = get_decrypted_password(entry)
    database = req.database_name
    try:
        conn = await asyncpg.connect(
            host=entry["host"], port=int(entry.get("port", 5432)),
            user=entry.get("username", ""), password=password, database="postgres",
        )
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", database)
        if exists:
            await conn.close()
            return CreateDatabaseResponse(success=True, message=f"Database '{database}' already exists", database=database)
        await conn.execute(f'CREATE DATABASE "{database}"')
        await conn.close()
        logger.info("Created target database", database=database)
        return CreateDatabaseResponse(success=True, message=f"Database '{database}' created successfully", database=database)
    except Exception as exc:
        logger.error("Failed to create database", database=database, error=str(exc))
        raise HTTPException(status_code=502, detail=f"Failed to create database: {exc}") from exc
