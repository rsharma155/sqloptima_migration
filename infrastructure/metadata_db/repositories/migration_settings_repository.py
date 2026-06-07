"""Repository for platform-wide migration job settings.

Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.metadata_db.models import PlatformMigrationSettingsRecord

DEFAULT_SETTINGS_ID = "platform-default"


class MigrationSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self) -> PlatformMigrationSettingsRecord | None:
        return await self._session.get(PlatformMigrationSettingsRecord, DEFAULT_SETTINGS_ID)

    async def upsert(
        self, record: PlatformMigrationSettingsRecord
    ) -> PlatformMigrationSettingsRecord:
        record.settings_id = DEFAULT_SETTINGS_ID
        record.updated_at = datetime.now(UTC)
        merged = await self._session.merge(record)
        await self._session.commit()
        return merged
