"""
Module: apps/api/routers/projects_router.py
Purpose: CRUD endpoints for migration projects.  A project pairs a source
         (SQL Server) connection with a target (PostgreSQL) connection and
         serves as the top-level grouping for all discovery, assessment and
         migration jobs.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from apps.api.middleware.auth import UserRole, require_role
from infrastructure.metadata_db.repositories.project_repository import ProjectRepository
from infrastructure.metadata_db.session import AsyncSessionFactory
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    source_connection_id: str | None = None
    target_connection_id: str | None = None


class ProjectUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    source_connection_id: str | None = None
    target_connection_id: str | None = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str | None
    source_connection_id: str | None
    target_connection_id: str | None
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_response(record) -> ProjectResponse:  # type: ignore[no-untyped-def]
    return ProjectResponse(
        id=str(record.project_id),
        name=record.name,
        description=record.description,
        source_connection_id=(
            str(record.source_project_connection_id) if record.source_project_connection_id else None
        ),
        target_connection_id=(
            str(record.target_project_connection_id) if record.target_project_connection_id else None
        ),
        created_at=record.created_at.isoformat() if record.created_at else "",
        updated_at=record.updated_at.isoformat() if record.updated_at else "",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    _: dict = require_role(UserRole.VIEWER),
) -> list[ProjectResponse]:
    """Return all projects (visible to all authenticated roles)."""
    async with AsyncSessionFactory() as session:
        repo = ProjectRepository(session)
        records = await repo.get_all()
    return [_to_response(r) for r in records]


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    req: ProjectCreateRequest,
    current_user: dict = require_role(UserRole.OPERATOR),
) -> ProjectResponse:
    """Create a new project.  Operators and Admins only."""
    async with AsyncSessionFactory() as session:
        repo = ProjectRepository(session)
        existing = await repo.get_by_name(req.name)
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Project with name {req.name!r} already exists",
            )
        user_id = current_user.get("sub") if isinstance(current_user, dict) else None
        record = await repo.create(
            name=req.name,
            source_connection_id=req.source_connection_id,
            target_connection_id=req.target_connection_id,
            description=req.description,
            created_by=str(user_id) if user_id else None,
        )
        await session.commit()
    logger.info("project_created", id=record.project_id, name=req.name)
    return _to_response(record)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    _: dict = require_role(UserRole.VIEWER),
) -> ProjectResponse:
    async with AsyncSessionFactory() as session:
        repo = ProjectRepository(session)
        record = await repo.get_by_id(str(project_id))
    if record is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return _to_response(record)


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    req: ProjectUpdateRequest,
    _: dict = require_role(UserRole.OPERATOR),
) -> ProjectResponse:
    """Update a project's name, description, or connection assignments."""
    async with AsyncSessionFactory() as session:
        repo = ProjectRepository(session)
        record = await repo.update(
            str(project_id),
            name=req.name,
            description=req.description,
            source_connection_id=req.source_connection_id,
            target_connection_id=req.target_connection_id,
        )
        if record is None:
            raise HTTPException(status_code=404, detail="Project not found")
        await session.commit()
    logger.info("project_updated", id=str(project_id))
    return _to_response(record)


@router.delete("/{project_id}", status_code=204, response_model=None)
async def delete_project(
    project_id: UUID,
    _: dict = require_role(UserRole.ADMIN),
) -> None:
    """Delete a project (Admin only)."""
    async with AsyncSessionFactory() as session:
        repo = ProjectRepository(session)
        deleted = await repo.delete(str(project_id))
        if not deleted:
            raise HTTPException(status_code=404, detail="Project not found")
        await session.commit()
    logger.info("project_deleted", id=str(project_id))
