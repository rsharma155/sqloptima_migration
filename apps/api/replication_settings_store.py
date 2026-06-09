"""In-memory cache + DB persistence for platform replication settings.

Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from infrastructure.metadata_db.models import PlatformReplicationSettingsRecord
from infrastructure.metadata_db.repositories.replication_settings_repository import (
    DEFAULT_SETTINGS_ID,
    ReplicationSettingsRepository,
)
from infrastructure.metadata_db.session import AsyncSessionFactory
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

_settings: dict[str, Any] | None = None


def _default_settings() -> dict[str, Any]:
    return {
        "poll_interval_ms": 1000,
        "batch_size": 1000,
        "updated_at": "",
    }


def _record_to_dict(record: PlatformReplicationSettingsRecord) -> dict[str, Any]:
    return {
        "poll_interval_ms": int(record.poll_interval_ms),
        "batch_size": int(record.batch_size),
        "updated_at": record.updated_at.isoformat() if record.updated_at else "",
    }


def _dict_to_record(data: dict[str, Any]) -> PlatformReplicationSettingsRecord:
    updated = data.get("updated_at")
    return PlatformReplicationSettingsRecord(
        settings_id=DEFAULT_SETTINGS_ID,
        poll_interval_ms=int(data.get("poll_interval_ms", 1000)),
        batch_size=int(data.get("batch_size", 1000)),
        updated_at=datetime.fromisoformat(updated) if updated else datetime.now(UTC),
    )


async def load_replication_settings() -> None:
    global _settings
    try:
        async with AsyncSessionFactory() as session:
            repo = ReplicationSettingsRepository(session)
            record = await repo.get()
        _settings = _record_to_dict(record) if record else _default_settings()
        logger.info("Replication settings loaded from DB", configured=bool(record))
    except Exception as exc:
        logger.warning("Failed to load replication settings, using defaults", error=str(exc))
        _settings = _default_settings()


def get_settings() -> dict[str, Any]:
    return dict(_settings or _default_settings())


def set_settings(data: dict[str, Any]) -> None:
    global _settings
    merged = {**_default_settings(), **(_settings or {}), **data}
    merged["updated_at"] = datetime.now(UTC).isoformat()
    _settings = merged


async def save_settings_async() -> None:
    if _settings is None:
        return
    try:
        async with AsyncSessionFactory() as session:
            repo = ReplicationSettingsRepository(session)
            await repo.upsert(_dict_to_record(_settings))
    except Exception as exc:
        logger.error("Failed to persist replication settings", error=str(exc))
        raise
