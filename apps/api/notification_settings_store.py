"""In-memory cache + DB persistence for platform notification settings.

Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from infrastructure.metadata_db.models import PlatformNotificationSettingsRecord
from infrastructure.metadata_db.repositories.notification_settings_repository import (
    DEFAULT_SETTINGS_ID,
    NotificationSettingsRepository,
)
from infrastructure.metadata_db.session import AsyncSessionFactory
from shared.logging.structured_logging import get_logger
from shared.security.secrets_manager import SecretsManager

logger = get_logger(__name__)

_settings: dict[str, Any] | None = None
_secrets_instance: SecretsManager | None = None


def set_secrets_manager(sm: SecretsManager | None) -> None:
    global _secrets_instance
    _secrets_instance = sm


def _default_settings() -> dict[str, Any]:
    return {
        "webhook_enabled": False,
        "webhook_url": "",
        "email_enabled": False,
        "smtp_host": "",
        "smtp_port": 587,
        "smtp_user": "",
        "smtp_password": "",
        "alert_email_to": "",
        "alert_email_from": "",
        "updated_at": "",
    }


def _record_to_dict(record: PlatformNotificationSettingsRecord) -> dict[str, Any]:
    return {
        "webhook_enabled": bool(record.webhook_enabled),
        "webhook_url": record.webhook_url_encrypted or "",
        "email_enabled": bool(record.email_enabled),
        "smtp_host": record.smtp_host or "",
        "smtp_port": int(record.smtp_port or 587),
        "smtp_user": record.smtp_user or "",
        "smtp_password": record.smtp_password_encrypted or "",
        "alert_email_to": record.alert_email_to or "",
        "alert_email_from": record.alert_email_from or "",
        "updated_at": record.updated_at.isoformat() if record.updated_at else "",
    }


def _dict_to_record(data: dict[str, Any]) -> PlatformNotificationSettingsRecord:
    updated = data.get("updated_at")
    return PlatformNotificationSettingsRecord(
        settings_id=DEFAULT_SETTINGS_ID,
        webhook_enabled=bool(data.get("webhook_enabled")),
        webhook_url_encrypted=data.get("webhook_url", ""),
        email_enabled=bool(data.get("email_enabled")),
        smtp_host=data.get("smtp_host", ""),
        smtp_port=int(data.get("smtp_port", 587)),
        smtp_user=data.get("smtp_user", ""),
        smtp_password_encrypted=data.get("smtp_password", ""),
        alert_email_to=data.get("alert_email_to", ""),
        alert_email_from=data.get("alert_email_from", ""),
        updated_at=datetime.fromisoformat(updated) if updated else datetime.now(UTC),
    )


async def load_notification_settings() -> None:
    global _settings
    try:
        async with AsyncSessionFactory() as session:
            repo = NotificationSettingsRepository(session)
            record = await repo.get()
        _settings = _record_to_dict(record) if record else _default_settings()
        logger.info("Notification settings loaded from DB", configured=bool(record))
    except Exception as exc:
        logger.warning("Failed to load notification settings, using defaults", error=str(exc))
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
            repo = NotificationSettingsRepository(session)
            await repo.upsert(_dict_to_record(_settings))
    except Exception as exc:
        logger.error("Failed to persist notification settings", error=str(exc))
        raise


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    if _secrets_instance:
        return _secrets_instance.encrypt(value)
    return value


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    if _secrets_instance and ":" in value:
        try:
            return _secrets_instance.decrypt(value)
        except Exception:
            logger.warning("Failed to decrypt notification secret, returning as-is")
    return value
