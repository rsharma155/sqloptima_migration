"""
Module: infrastructure/metadata_db/repositories/connection_repository.py
Purpose: Repository for project_connections — CRUD and test-status updates.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.metadata_db.models import ConnectionRecord


class ConnectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def get_all(self, project_id: str | None = None) -> list[ConnectionRecord]:
        stmt = select(ConnectionRecord).order_by(ConnectionRecord.name)
        if project_id:
            stmt = stmt.where(ConnectionRecord.project_id == project_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, connection_id: str) -> ConnectionRecord | None:
        return await self._session.get(ConnectionRecord, connection_id)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    async def create(
        self,
        *,
        id_: str | None = None,
        name: str,
        db_type: str,
        host: str,
        port: int,
        database_name: str,
        username: str,
        encrypted_password: str = "",
        ssl_enabled: bool = False,
        project_id: str | None = None,
    ) -> ConnectionRecord:
        """Insert and return a new connection record."""
        record = ConnectionRecord(
            project_connection_id=id_ or str(uuid4()),
            name=name,
            db_type=db_type,
            host=host,
            port=port,
            database_name=database_name,
            username=username,
            encrypted_password=encrypted_password,
            ssl_enabled=ssl_enabled,
            project_id=project_id,
            created_at=datetime.now(UTC),
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def update(
        self,
        connection_id: str,
        *,
        name: str | None = None,
        host: str | None = None,
        port: int | None = None,
        database_name: str | None = None,
        username: str | None = None,
        encrypted_password: str | None = None,
        ssl_enabled: bool | None = None,
    ) -> ConnectionRecord | None:
        """Update mutable fields; returns None if the record does not exist."""
        record = await self.get_by_id(connection_id)
        if record is None:
            return None
        if name is not None:
            record.name = name
        if host is not None:
            record.host = host
        if port is not None:
            record.port = port
        if database_name is not None:
            record.database_name = database_name
        if username is not None:
            record.username = username
        if encrypted_password is not None:
            record.encrypted_password = encrypted_password
        if ssl_enabled is not None:
            record.ssl_enabled = ssl_enabled
        await self._session.flush()
        return record

    async def upsert(self, record: ConnectionRecord) -> ConnectionRecord:
        """Merge an existing record (preserves backward compat with connection_store)."""
        merged = await self._session.merge(record)
        await self._session.commit()
        return merged

    async def delete(self, connection_id: str) -> bool:
        record = await self.get_by_id(connection_id)
        if not record:
            return False
        await self._session.delete(record)
        await self._session.flush()
        return True

    async def update_test_status(
        self,
        connection_id: str,
        ok: bool,
        tested_at: datetime | None = None,
    ) -> None:
        """Record the outcome of a connectivity test."""
        record = await self.get_by_id(connection_id)
        if record:
            record.last_tested_at = tested_at or datetime.now(UTC)
            record.last_test_ok = ok
            await self._session.flush()
