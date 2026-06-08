"""In-memory cache + DB persistence for platform migration settings.

Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from infrastructure.metadata_db.models import PlatformMigrationSettingsRecord
from infrastructure.metadata_db.repositories.migration_settings_repository import (
    DEFAULT_SETTINGS_ID,
    MigrationSettingsRepository,
)
from infrastructure.metadata_db.session import AsyncSessionFactory
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

_settings: dict[str, Any] | None = None


def _default_settings() -> dict[str, Any]:
    return {
        "source_throttle_enabled": True,
        "small_table_delay_sec": 1.0,
        "large_table_delay_sec": 4.0,
        "large_table_row_threshold": 100_000,
        "large_table_size_mb_threshold": 50.0,
        "max_tables_per_job": 25,
        "updated_at": "",
    }


def _record_to_dict(record: PlatformMigrationSettingsRecord) -> dict[str, Any]:
    return {
        "source_throttle_enabled": bool(record.source_throttle_enabled),
        "small_table_delay_sec": float(record.small_table_delay_sec),
        "large_table_delay_sec": float(record.large_table_delay_sec),
        "large_table_row_threshold": int(record.large_table_row_threshold),
        "large_table_size_mb_threshold": float(record.large_table_size_mb_threshold),
        "max_tables_per_job": int(record.max_tables_per_job),
        "updated_at": record.updated_at.isoformat() if record.updated_at else "",
    }


def _dict_to_record(data: dict[str, Any]) -> PlatformMigrationSettingsRecord:
    updated = data.get("updated_at")
    return PlatformMigrationSettingsRecord(
        settings_id=DEFAULT_SETTINGS_ID,
        source_throttle_enabled=bool(data.get("source_throttle_enabled", True)),
        small_table_delay_sec=float(data.get("small_table_delay_sec", 1.0)),
        large_table_delay_sec=float(data.get("large_table_delay_sec", 4.0)),
        large_table_row_threshold=int(data.get("large_table_row_threshold", 100_000)),
        large_table_size_mb_threshold=float(data.get("large_table_size_mb_threshold", 50.0)),
        max_tables_per_job=int(data.get("max_tables_per_job", 25)),
        updated_at=datetime.fromisoformat(updated) if updated else datetime.now(UTC),
    )


async def load_migration_settings() -> None:
    global _settings
    try:
        async with AsyncSessionFactory() as session:
            repo = MigrationSettingsRepository(session)
            record = await repo.get()
        _settings = _record_to_dict(record) if record else _default_settings()
        logger.info("Migration settings loaded from DB", configured=bool(record))
    except Exception as exc:
        logger.warning("Failed to load migration settings, using defaults", error=str(exc))
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
            repo = MigrationSettingsRepository(session)
            await repo.upsert(_dict_to_record(_settings))
    except Exception as exc:
        logger.error("Failed to persist migration settings", error=str(exc))
        raise
