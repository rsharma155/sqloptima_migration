"""
Module: durable_migration_job_log_writer.py
Purpose: Persist migration job log lines to the metadata DB.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime

from infrastructure.metadata_db.repositories.migration_job_log_repository import (
    MigrationJobLogRepository,
)
from infrastructure.metadata_db.session import AsyncSessionFactory


class DurableMigrationJobLogWriter:
    async def append(self, job_id: str, message: str, *, level: str = "info") -> None:
        async with AsyncSessionFactory() as session:
            repo = MigrationJobLogRepository(session)
            await repo.append(job_id, message, level=level, logged_at=datetime.now(UTC))
