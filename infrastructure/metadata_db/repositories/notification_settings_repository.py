"""Repository for platform-wide notification / alerting settings.

Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.metadata_db.models import PlatformNotificationSettingsRecord

DEFAULT_SETTINGS_ID = "platform-default"


class NotificationSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self) -> PlatformNotificationSettingsRecord | None:
        return await self._session.get(PlatformNotificationSettingsRecord, DEFAULT_SETTINGS_ID)

    async def upsert(self, record: PlatformNotificationSettingsRecord) -> PlatformNotificationSettingsRecord:
        record.settings_id = DEFAULT_SETTINGS_ID
        record.updated_at = datetime.now(UTC)
        merged = await self._session.merge(record)
        await self._session.commit()
        return merged
