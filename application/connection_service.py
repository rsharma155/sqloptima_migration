"""
Module: application/connection_service.py
Purpose: Application service for connection lifecycle — create, test, update,
         delete and list source/target database connections.  Encrypts
         passwords via SecretsManager before persistence.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.metadata_db.repositories.connection_repository import ConnectionRepository
from shared.logging.structured_logging import get_logger
from shared.security.secrets_manager import SecretsManager

logger = get_logger(__name__)


@dataclass
class ConnectionCreateRequest:
    name: str
    db_type: str          # 'sqlserver' | 'postgresql'
    host: str
    port: int
    database_name: str
    username: str
    password: str
    ssl_enabled: bool = False


@dataclass
class ConnectionDTO:
    id: str
    name: str
    db_type: str
    host: str
    port: int
    database_name: str
    username: str
    ssl_enabled: bool
    created_at: str
    last_tested_at: str | None
    last_test_ok: bool | None


class ConnectionServiceError(Exception):
    pass


class ConnectionService:
    """Manages connection profiles: encryption, persistence, and connectivity tests.

    Passwords are *always* encrypted with :class:`SecretsManager` before reaching
    the database.  They are *never* returned in plaintext via :meth:`list_all` or
    :meth:`get_by_id` — callers that need to connect must use
    :meth:`decrypt_password`.
    """

    def __init__(self, session: AsyncSession, secrets: SecretsManager) -> None:
        self._repo = ConnectionRepository(session)
        self._secrets = secrets

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def list_all(self) -> list[ConnectionDTO]:
        records = await self._repo.get_all()
        return [self._to_dto(r) for r in records]

    async def get_by_id(self, conn_id: str) -> ConnectionDTO:
        record = await self._repo.get_by_id(conn_id)
        if record is None:
            raise ConnectionServiceError(f"Connection {conn_id!r} not found")
        return self._to_dto(record)

    async def decrypt_password(self, conn_id: str) -> str:
        """Return the plaintext password for *conn_id*.  Raises on missing."""
        record = await self._repo.get_by_id(conn_id)
        if record is None:
            raise ConnectionServiceError(f"Connection {conn_id!r} not found")
        if not record.encrypted_password:
            return ""
        return self._secrets.decrypt(record.encrypted_password)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    async def create(self, req: ConnectionCreateRequest) -> ConnectionDTO:
        """Create and persist a new connection profile."""
        if req.db_type not in ("sqlserver", "postgresql"):
            raise ConnectionServiceError(
                f"Unsupported db_type {req.db_type!r}; must be 'sqlserver' or 'postgresql'"
            )
        encrypted = self._secrets.encrypt(req.password) if req.password else ""
        record = await self._repo.create(
            id_=str(uuid4()),
            name=req.name,
            db_type=req.db_type,
            host=req.host,
            port=req.port,
            database_name=req.database_name,
            username=req.username,
            encrypted_password=encrypted,
            ssl_enabled=req.ssl_enabled,
        )
        logger.info(
            "connection_created",
            id=record.project_connection_id,
            name=req.name,
            db_type=req.db_type,
            host=req.host,
        )
        return self._to_dto(record)

    async def update(
        self,
        conn_id: str,
        name: str | None = None,
        host: str | None = None,
        port: int | None = None,
        database_name: str | None = None,
        username: str | None = None,
        password: str | None = None,
        ssl_enabled: bool | None = None,
    ) -> ConnectionDTO:
        """Update mutable fields; password is re-encrypted if provided."""
        record = await self._repo.get_by_id(conn_id)
        if record is None:
            raise ConnectionServiceError(f"Connection {conn_id!r} not found")

        encrypted_password = (
            self._secrets.encrypt(password) if password is not None else None
        )
        updated = await self._repo.update(
            conn_id,
            name=name,
            host=host,
            port=port,
            database_name=database_name,
            username=username,
            encrypted_password=encrypted_password,
            ssl_enabled=ssl_enabled,
        )
        if updated is None:
            raise ConnectionServiceError(f"Connection {conn_id!r} not found")
        logger.info("connection_updated", id=conn_id)
        return self._to_dto(updated)

    async def delete(self, conn_id: str) -> None:
        deleted = await self._repo.delete(conn_id)
        if not deleted:
            raise ConnectionServiceError(f"Connection {conn_id!r} not found")
        logger.info("connection_deleted", id=conn_id)

    async def record_test_result(self, conn_id: str, success: bool) -> None:
        """Persist the outcome of a connectivity test."""
        await self._repo.update_test_status(conn_id, success, datetime.now(UTC))

    # keep backward compat — datetime import is used above

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_dto(record: Any) -> ConnectionDTO:
        return ConnectionDTO(
            id=str(record.project_connection_id),
            name=record.name,
            db_type=record.db_type,
            host=record.host,
            port=record.port,
            database_name=record.database_name,
            username=record.username,
            ssl_enabled=bool(record.ssl_enabled),
            created_at=record.created_at.isoformat() if record.created_at else "",
            last_tested_at=(
                record.last_tested_at.isoformat() if record.last_tested_at else None
            ),
            last_test_ok=record.last_test_ok,
        )
