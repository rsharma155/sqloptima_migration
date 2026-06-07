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


class WaveSignOffRequest(BaseModel):
    approver: str


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
    _: dict = require_role(UserRole.VIEWER),
):
    require_feature("programs")
    async with AsyncSessionFactory() as session:
        repo = MigrationProgramRepository(session)
        programs = await repo.list_programs(str(project_id) if project_id else None)
        await session.commit()
        return [_program_dict(p) for p in programs]


@router.post("")
async def create_program(req: ProgramCreateRequest, _: dict = require_role(UserRole.OPERATOR)):
    require_feature("programs")
    async with AsyncSessionFactory() as session:
        repo = MigrationProgramRepository(session)
        program = await repo.create_program(
            str(req.project_id), req.name, owner=req.owner, notes=req.notes
        )
        await session.commit()
        return _program_dict(program)


@router.get("/{program_id}")
async def get_program(program_id: UUID, _: dict = require_role(UserRole.VIEWER)):
    async with AsyncSessionFactory() as session:
        repo = MigrationProgramRepository(session)
        program = await repo.get_program(str(program_id))
        if not program:
            raise HTTPException(status_code=404, detail="Program not found")
        return _program_dict(program)


@router.post("/{program_id}/waves")
async def add_wave(
    program_id: UUID,
    req: WaveCreateRequest,
    _: dict = require_role(UserRole.OPERATOR),
):
    async with AsyncSessionFactory() as session:
        repo = MigrationProgramRepository(session)
        try:
            wave = await repo.add_wave(
                str(program_id),
                req.name,
                req.tables,
                wave_number=req.wave_number,
                schema_name=req.schema_name,
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
        }


@router.post("/waves/{wave_id}/sign-off")
async def sign_off_wave(
    wave_id: UUID,
    req: WaveSignOffRequest,
    _: dict = require_role(UserRole.OPERATOR),
):
    async with AsyncSessionFactory() as session:
        repo = MigrationProgramRepository(session)
        wave = await repo.sign_off_wave(str(wave_id), req.approver)
        if not wave:
            raise HTTPException(status_code=404, detail="Wave not found")
        await session.commit()
        return {
            "id": wave.migration_wave_id,
            "status": wave.status,
            "approver": wave.approver,
            "signed_off_at": wave.signed_off_at.isoformat() if wave.signed_off_at else None,
        }
