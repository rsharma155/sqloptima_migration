"""Migration program / wave management API (§13.1).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from apps.api.middleware.auth import UserRole, require_role
from domains.licensing.editions import require_feature
from infrastructure.metadata_db.repositories.migration_program_repository import (
    MigrationProgramRepository,
)
from infrastructure.metadata_db.session import AsyncSessionFactory
from shared.tenancy.project_scope import (
    assert_resource_project_access,
    resolve_project_filter,
)

router = APIRouter(prefix="/programs", tags=["programs"])


class ProgramCreateRequest(BaseModel):
    project_id: UUID
    name: str
    owner: str | None = None
    notes: str | None = None


class WaveCreateRequest(BaseModel):
    name: str
    tables: list[str] = Field(min_length=1)
    schema_name: str = "dbo"
    wave_number: int | None = None
    cutover_window_start: datetime | None = None
    cutover_window_end: datetime | None = None


class WaveSignOffRequest(BaseModel):
    approver: str


class WaveScheduleRequest(BaseModel):
    cutover_window_start: datetime | None = None
    cutover_window_end: datetime | None = None


def _is_admin(user: dict) -> bool:
    return user.get("role") == UserRole.ADMIN.value


def _assert_program_access(program, user: dict) -> None:
    assert_resource_project_access(
        getattr(program, "project_id", None),
        user_project_id=user.get("project_id"),
        is_admin=_is_admin(user),
    )


def _program_dict(p) -> dict:
    return {
        "id": p.migration_program_id,
        "project_id": p.project_id,
        "name": p.name,
        "status": p.status,
        "owner": p.owner,
        "notes": p.notes,
        "waves": [
            {
                "id": w.migration_wave_id,
                "wave_number": w.wave_number,
                "name": w.name,
                "tables": w.tables,
                "schema_name": w.schema_name,
                "status": w.status,
                "cutover_window_start": (
                    w.cutover_window_start.isoformat() if w.cutover_window_start else None
                ),
                "cutover_window_end": (
                    w.cutover_window_end.isoformat() if w.cutover_window_end else None
                ),
                "approver": w.approver,
                "signed_off_at": w.signed_off_at.isoformat() if w.signed_off_at else None,
                "job_id": w.migration_job_id,
            }
            for w in (p.waves or [])
        ],
    }


@router.get("")
async def list_programs(
    project_id: UUID | None = None,
    user: dict = require_role(UserRole.VIEWER),
):
    require_feature("programs")
    scope = resolve_project_filter(
        str(project_id) if project_id else None,
        user_project_id=user.get("project_id"),
        is_admin=_is_admin(user),
    )
    async with AsyncSessionFactory() as session:
        repo = MigrationProgramRepository(session)
        programs = await repo.list_programs(scope)
        await session.commit()
        return [_program_dict(p) for p in programs]


@router.post("")
async def create_program(req: ProgramCreateRequest, user: dict = require_role(UserRole.OPERATOR)):
    require_feature("programs")
    # Pin create to the caller's project when the JWT carries a project_id claim.
    scope = resolve_project_filter(
        str(req.project_id),
        user_project_id=user.get("project_id"),
        is_admin=_is_admin(user),
    )
    if not scope:
        raise HTTPException(status_code=400, detail="project_id is required")
    async with AsyncSessionFactory() as session:
        repo = MigrationProgramRepository(session)
        program = await repo.create_program(
            scope, req.name, owner=req.owner, notes=req.notes
        )
        await session.commit()
        return _program_dict(program)


@router.get("/{program_id}")
async def get_program(program_id: UUID, user: dict = require_role(UserRole.VIEWER)):
    async with AsyncSessionFactory() as session:
        repo = MigrationProgramRepository(session)
        program = await repo.get_program(str(program_id))
        if not program:
            raise HTTPException(status_code=404, detail="Program not found")
        _assert_program_access(program, user)
        return _program_dict(program)


@router.post("/{program_id}/waves")
async def add_wave(
    program_id: UUID,
    req: WaveCreateRequest,
    user: dict = require_role(UserRole.OPERATOR),
):
    async with AsyncSessionFactory() as session:
        repo = MigrationProgramRepository(session)
        program = await repo.get_program(str(program_id))
        if not program:
            raise HTTPException(status_code=404, detail="Program not found")
        _assert_program_access(program, user)
        try:
            wave = await repo.add_wave(
                str(program_id),
                req.name,
                req.tables,
                wave_number=req.wave_number,
                schema_name=req.schema_name,
                cutover_window_start=req.cutover_window_start,
                cutover_window_end=req.cutover_window_end,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        await session.commit()
        return {
            "id": wave.migration_wave_id,
            "program_id": wave.migration_program_id,
            "wave_number": wave.wave_number,
            "name": wave.name,
            "tables": wave.tables,
            "status": wave.status,
            "cutover_window_start": (
                wave.cutover_window_start.isoformat() if wave.cutover_window_start else None
            ),
            "cutover_window_end": (
                wave.cutover_window_end.isoformat() if wave.cutover_window_end else None
            ),
        }


async def _load_wave_program(repo: MigrationProgramRepository, wave_id: str, user: dict):
    wave = await repo.get_wave(wave_id)
    if not wave:
        raise HTTPException(status_code=404, detail="Wave not found")
    program = await repo.get_program(wave.migration_program_id)
    if not program:
        raise HTTPException(status_code=404, detail="Program not found")
    _assert_program_access(program, user)
    return wave, program


@router.patch("/waves/{wave_id}/schedule")
async def schedule_wave(
    wave_id: UUID,
    req: WaveScheduleRequest,
    user: dict = require_role(UserRole.OPERATOR),
):
    async with AsyncSessionFactory() as session:
        repo = MigrationProgramRepository(session)
        await _load_wave_program(repo, str(wave_id), user)
        wave = await repo.set_cutover_window(
            str(wave_id),
            cutover_window_start=req.cutover_window_start,
            cutover_window_end=req.cutover_window_end,
        )
        await session.commit()
        return {
            "id": wave.migration_wave_id,
            "cutover_window_start": (
                wave.cutover_window_start.isoformat() if wave.cutover_window_start else None
            ),
            "cutover_window_end": (
                wave.cutover_window_end.isoformat() if wave.cutover_window_end else None
            ),
        }


@router.post("/waves/{wave_id}/sign-off")
async def sign_off_wave(
    wave_id: UUID,
    req: WaveSignOffRequest,
    user: dict = require_role(UserRole.OPERATOR),
):
    async with AsyncSessionFactory() as session:
        repo = MigrationProgramRepository(session)
        await _load_wave_program(repo, str(wave_id), user)
        wave = await repo.sign_off_wave(str(wave_id), req.approver)
        await session.commit()
        return {
            "id": wave.migration_wave_id,
            "status": wave.status,
            "approver": wave.approver,
            "signed_off_at": wave.signed_off_at.isoformat() if wave.signed_off_at else None,
        }
