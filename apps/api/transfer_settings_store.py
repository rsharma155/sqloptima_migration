"""In-memory cache + DB persistence for platform Transfer settings.

Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from domains.transfer.transfer_settings import default_transfer_settings, validate_transfer_settings
from infrastructure.metadata_db.models import PlatformTransferSettingsRecord
from infrastructure.metadata_db.repositories.transfer_settings_repository import (
    DEFAULT_SETTINGS_ID,
    TransferSettingsRepository,
)
from infrastructure.metadata_db.session import AsyncSessionFactory
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

_settings: dict[str, Any] | None = None


def _record_to_dict(record: PlatformTransferSettingsRecord) -> dict[str, Any]:
    return {
        "file_offload_enabled": bool(record.file_offload_enabled),
        "file_offload_min_rows": int(record.file_offload_min_rows),
        "file_offload_min_mb": float(record.file_offload_min_mb),
        "staging_path": str(record.staging_path or ""),
        "updated_at": record.updated_at.isoformat() if record.updated_at else "",
    }


def _dict_to_record(data: dict[str, Any]) -> PlatformTransferSettingsRecord:
    validated = validate_transfer_settings(data)
    updated = data.get("updated_at")
    return PlatformTransferSettingsRecord(
        settings_id=DEFAULT_SETTINGS_ID,
        file_offload_enabled=validated["file_offload_enabled"],
        file_offload_min_rows=validated["file_offload_min_rows"],
        file_offload_min_mb=validated["file_offload_min_mb"],
        staging_path=validated["staging_path"],
        updated_at=datetime.fromisoformat(updated) if updated else datetime.now(UTC),
    )


async def load_transfer_settings() -> None:
    global _settings
    try:
        async with AsyncSessionFactory() as session:
            repo = TransferSettingsRepository(session)
            record = await repo.get()
        _settings = _record_to_dict(record) if record else default_transfer_settings()
        logger.info("Transfer settings loaded from DB", configured=bool(record))
    except Exception as exc:
        logger.warning("Failed to load transfer settings, using defaults", error=str(exc))
        _settings = default_transfer_settings()


def get_settings() -> dict[str, Any]:
    return dict(_settings or default_transfer_settings())


def set_settings(data: dict[str, Any]) -> None:
    global _settings
    merged = {**default_transfer_settings(), **(_settings or {}), **data}
    validated = validate_transfer_settings(merged)
    validated["updated_at"] = datetime.now(UTC).isoformat()
    _settings = validated


async def save_settings_async() -> None:
    if _settings is None:
        return
    try:
        async with AsyncSessionFactory() as session:
            repo = TransferSettingsRepository(session)
            await repo.upsert(_dict_to_record(_settings))
    except Exception as exc:
        logger.error("Failed to persist transfer settings", error=str(exc))
        raise
