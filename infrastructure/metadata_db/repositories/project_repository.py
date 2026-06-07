"""
Module: infrastructure/metadata_db/repositories/project_repository.py
Purpose: Repository for project_projects rows — groups a source and target
         connection into a named migration project.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.metadata_db.models import ProjectRecord


class ProjectRepository:
    """CRUD for project_projects rows.

    A *project* is the top-level entity that pairs a SQL Server source
    connection with a PostgreSQL target connection and owns all discovery,
    assessment, and migration jobs.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def get_all(self) -> list[ProjectRecord]:
        result = await self._session.execute(
            select(ProjectRecord).order_by(ProjectRecord.name)
        )
        return list(result.scalars().all())

    async def get_by_id(self, project_id: str) -> ProjectRecord | None:
        result = await self._session.execute(
            select(ProjectRecord).where(ProjectRecord.project_id == project_id)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> ProjectRecord | None:
        result = await self._session.execute(
            select(ProjectRecord).where(ProjectRecord.name == name)
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    async def create(
        self,
        name: str,
        source_connection_id: str | None = None,
        target_connection_id: str | None = None,
        description: str | None = None,
        created_by: str | None = None,
    ) -> ProjectRecord:
        """Insert and return a new project."""
        now = datetime.now(UTC)
        project = ProjectRecord(
            project_id=str(uuid4()),
            name=name,
            description=description,
            source_project_connection_id=source_connection_id,
            target_project_connection_id=target_connection_id,
            created_by_auth_user_id=created_by,
            created_at=now,
            updated_at=now,
        )
        self._session.add(project)
        await self._session.flush()
        return project

    async def update(
        self,
        project_id: str,
        name: str | None = None,
        description: str | None = None,
        source_connection_id: str | None = None,
        target_connection_id: str | None = None,
    ) -> ProjectRecord | None:
        """Update mutable fields; returns None if not found."""
        project = await self.get_by_id(project_id)
        if project is None:
            return None
        if name is not None:
            project.name = name
        if description is not None:
            project.description = description
        if source_connection_id is not None:
            project.source_project_connection_id = source_connection_id
        if target_connection_id is not None:
            project.target_project_connection_id = target_connection_id
        project.updated_at = datetime.now(UTC)
        await self._session.flush()
        return project

    async def delete(self, project_id: str) -> bool:
        """Delete a project; returns True if it existed."""
        project = await self.get_by_id(project_id)
        if project is None:
            return False
        await self._session.delete(project)
        await self._session.flush()
        return True
