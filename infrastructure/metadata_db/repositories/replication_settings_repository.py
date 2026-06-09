"""Repository for platform-wide replication capture settings.

Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.metadata_db.models import PlatformReplicationSettingsRecord

DEFAULT_SETTINGS_ID = "platform-default"


class ReplicationSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self) -> PlatformReplicationSettingsRecord | None:
        return await self._session.get(PlatformReplicationSettingsRecord, DEFAULT_SETTINGS_ID)

    async def upsert(
        self, record: PlatformReplicationSettingsRecord
    ) -> PlatformReplicationSettingsRecord:
        record.settings_id = DEFAULT_SETTINGS_ID
        record.updated_at = datetime.now(UTC)
        merged = await self._session.merge(record)
        await self._session.commit()
        return merged
