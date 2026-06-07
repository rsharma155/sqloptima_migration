"""
Module: migration_job_log_reader.py
Purpose: Load durable migration job logs from the metadata DB for API responses.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from infrastructure.metadata_db.repositories.migration_job_log_repository import (
    MigrationJobLogRepository,
)
from infrastructure.metadata_db.session import AsyncSessionFactory


async def load_durable_migration_job_logs(job_id: str) -> list[dict[str, str]]:
    async with AsyncSessionFactory() as session:
        repo = MigrationJobLogRepository(session)
        records = await repo.list_for_job(job_id)
        return [
            {
                "timestamp": r.logged_at.isoformat(),
                "level": r.level,
                "message": r.message,
            }
            for r in records
        ]
