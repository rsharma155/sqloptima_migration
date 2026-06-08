"""Resolve effective notification channel configuration (DB + env fallback).

Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import os
from typing import Any

from apps.api.notification_settings_store import decrypt_secret, get_settings


def _mask_secret(value: str, *, visible_tail: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= visible_tail + 3:
        return "••••••"
    return f"{'•' * 8}{value[-visible_tail:]}"


def _mask_url(url: str) -> str:
    if not url:
        return ""
    if len(url) <= 24:
        return "••••••"
    return f"{url[:20]}…{_mask_secret(url, visible_tail=4)}"


def resolved_notification_config() -> dict[str, Any]:
    """Effective config used by NotificationService (secrets decrypted)."""
    stored = get_settings()
    webhook_url = ""
    if stored.get("webhook_enabled") and stored.get("webhook_url"):
        webhook_url = decrypt_secret(stored["webhook_url"])
    elif os.environ.get("MIGRATION_WEBHOOK_URL"):
        webhook_url = os.environ["MIGRATION_WEBHOOK_URL"]

    smtp_host = ""
    smtp_port = 587
    smtp_user = ""
    smtp_password = ""
    alert_email_to = ""
    alert_email_from = ""

    if stored.get("email_enabled"):
        smtp_host = stored.get("smtp_host", "")
        smtp_port = int(stored.get("smtp_port", 587))
        smtp_user = stored.get("smtp_user", "")
        smtp_password = decrypt_secret(stored.get("smtp_password", ""))
        alert_email_to = stored.get("alert_email_to", "")
        alert_email_from = stored.get("alert_email_from", "") or smtp_user
    else:
        smtp_host = os.environ.get("MIGRATION_SMTP_HOST", "")
        smtp_port = int(os.environ.get("MIGRATION_SMTP_PORT", "587"))
        smtp_user = os.environ.get("MIGRATION_SMTP_USER", "")
        smtp_password = os.environ.get("MIGRATION_SMTP_PASSWORD", "")
        alert_email_to = os.environ.get("MIGRATION_ALERT_EMAIL_TO", "")
        alert_email_from = (
            os.environ.get("MIGRATION_ALERT_EMAIL_FROM")
            or smtp_user
            or "alerts@sql-optima.local"
        )

    webhook_configured = bool(webhook_url)
    email_configured = bool(smtp_host and alert_email_to)

    db_webhook = bool(stored.get("webhook_enabled") and stored.get("webhook_url"))
    db_email = bool(
        stored.get("email_enabled") and stored.get("smtp_host") and stored.get("alert_email_to")
    )
    env_webhook = bool(os.environ.get("MIGRATION_WEBHOOK_URL"))
    env_email = bool(os.environ.get("MIGRATION_SMTP_HOST") and os.environ.get("MIGRATION_ALERT_EMAIL_TO"))

    if db_webhook or db_email:
        source = "database"
    elif env_webhook or env_email:
        source = "environment"
    else:
        source = "none"

    return {
        "webhook_url": webhook_url,
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "smtp_user": smtp_user,
        "smtp_password": smtp_password,
        "alert_email_to": alert_email_to,
        "alert_email_from": alert_email_from,
        "webhook_configured": webhook_configured,
        "email_configured": email_configured,
        "channels_active": webhook_configured or email_configured,
        "source": source,
    }


def notification_config_status() -> dict[str, Any]:
    """Public API/UI view — secrets masked."""
    stored = get_settings()
    effective = resolved_notification_config()
    smtp_password_set = bool(
        (stored.get("email_enabled") and stored.get("smtp_password"))
        or os.environ.get("MIGRATION_SMTP_PASSWORD")
    )
    return {
        "webhook_enabled": bool(stored.get("webhook_enabled")),
        "webhook_configured": effective["webhook_configured"],
        "webhook_url": _mask_url(effective["webhook_url"]) if effective["webhook_url"] else "",
        "email_enabled": bool(stored.get("email_enabled")),
        "email_configured": effective["email_configured"],
        "email_to": effective["alert_email_to"] if effective["email_configured"] else None,
        "smtp_host": stored.get("smtp_host", "") if stored.get("email_enabled") else "",
        "smtp_port": int(stored.get("smtp_port", 587)) if stored.get("email_enabled") else 587,
        "smtp_user": stored.get("smtp_user", "") if stored.get("email_enabled") else "",
        "smtp_password_set": smtp_password_set,
        "alert_email_to": stored.get("alert_email_to", "") if stored.get("email_enabled") else "",
        "alert_email_from": stored.get("alert_email_from", "") if stored.get("email_enabled") else "",
        "channels_active": effective["channels_active"],
        "source": effective["source"],
        "updated_at": stored.get("updated_at") or None,
    }
