"""Repository for migration program / wave rows (§13.1).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes as orm_attributes
from infrastructure.metadata_db.models import MigrationProgramRecord, MigrationWaveRecord


class MigrationProgramRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _attach_waves(self, programs: list[MigrationProgramRecord]) -> None:
        if not programs:
            return
        ids = [p.migration_program_id for p in programs]
        result = await self._session.execute(
            select(MigrationWaveRecord)
            .where(MigrationWaveRecord.migration_program_id.in_(ids))
            .order_by(MigrationWaveRecord.wave_number)
        )
        by_program: dict[str, list[MigrationWaveRecord]] = {}
        for wave in result.scalars().all():
            by_program.setdefault(wave.migration_program_id, []).append(wave)
        for program in programs:
            orm_attributes.set_committed_value(
                program, "waves", by_program.get(program.migration_program_id, [])
            )

    async def list_programs(self, project_id: str | None = None) -> list[MigrationProgramRecord]:
        stmt = select(MigrationProgramRecord)
        if project_id:
            stmt = stmt.where(MigrationProgramRecord.project_id == project_id)
        stmt = stmt.order_by(MigrationProgramRecord.name)
        result = await self._session.execute(stmt)
        programs = list(result.scalars().all())
        await self._attach_waves(programs)
        return programs

    async def get_program(self, program_id: str) -> MigrationProgramRecord | None:
        result = await self._session.execute(
            select(MigrationProgramRecord).where(MigrationProgramRecord.migration_program_id == program_id)
        )
        program = result.scalar_one_or_none()
        if program:
            await self._attach_waves([program])
        return program

    async def create_program(
        self,
        project_id: str,
        name: str,
        *,
        owner: str | None = None,
        notes: str | None = None,
    ) -> MigrationProgramRecord:
        now = datetime.now(UTC)
        program = MigrationProgramRecord(
            migration_program_id=str(uuid4()),
            project_id=project_id,
            name=name,
            status="planning",
            owner=owner,
            notes=notes,
            created_at=now,
            updated_at=now,
        )
        self._session.add(program)
        await self._session.flush()
        return program

    async def add_wave(
        self,
        program_id: str,
        name: str,
        tables: list[str],
        *,
        wave_number: int | None = None,
        schema_name: str = "dbo",
        cutover_window_start: datetime | None = None,
        cutover_window_end: datetime | None = None,
    ) -> MigrationWaveRecord:
        result = await self._session.execute(
            select(MigrationProgramRecord).where(MigrationProgramRecord.migration_program_id == program_id)
        )
        program = result.scalar_one_or_none()
        if not program:
            raise ValueError(f"Program not found: {program_id}")
        count_result = await self._session.execute(
            select(func.count())
            .select_from(MigrationWaveRecord)
            .where(MigrationWaveRecord.migration_program_id == program_id)
        )
        existing = int(count_result.scalar_one() or 0)
        next_num = wave_number or (existing + 1)
        now = datetime.now(UTC)
        wave = MigrationWaveRecord(
            migration_wave_id=str(uuid4()),
            migration_program_id=program_id,
            wave_number=next_num,
            name=name,
            tables=tables,
            schema_name=schema_name,
            status="pending",
            cutover_window_start=cutover_window_start,
            cutover_window_end=cutover_window_end,
            created_at=now,
            updated_at=now,
        )
        self._session.add(wave)
        await self._session.flush()
        return wave

    async def get_wave(self, wave_id: str) -> MigrationWaveRecord | None:
        result = await self._session.execute(
            select(MigrationWaveRecord).where(MigrationWaveRecord.migration_wave_id == wave_id)
        )
        return result.scalar_one_or_none()

    async def set_cutover_window(
        self,
        wave_id: str,
        *,
        cutover_window_start: datetime | None,
        cutover_window_end: datetime | None,
    ) -> MigrationWaveRecord | None:
        result = await self._session.execute(
            select(MigrationWaveRecord).where(MigrationWaveRecord.migration_wave_id == wave_id)
        )
        wave = result.scalar_one_or_none()
        if not wave:
            return None
        wave.cutover_window_start = cutover_window_start
        wave.cutover_window_end = cutover_window_end
        wave.updated_at = datetime.now(UTC)
        await self._session.flush()
        return wave

    async def sign_off_wave(self, wave_id: str, approver: str) -> MigrationWaveRecord | None:
        result = await self._session.execute(
            select(MigrationWaveRecord).where(MigrationWaveRecord.migration_wave_id == wave_id)
        )
        wave = result.scalar_one_or_none()
        if not wave:
            return None
        wave.approver = approver
        wave.signed_off_at = datetime.now(UTC)
        wave.status = "approved"
        wave.updated_at = datetime.now(UTC)
        await self._session.flush()
        return wave
