"""Unit tests for notification config resolution and persistence."""

from __future__ import annotations

import pytest

from application.notification_config import (
    notification_config_status,
    resolved_notification_config,
)
from apps.api.notification_settings_store import encrypt_secret, set_settings


@pytest.fixture(autouse=True)
def _reset_settings():
    set_settings(
        {
            "webhook_enabled": False,
            "webhook_url": "",
            "email_enabled": False,
            "smtp_host": "",
            "smtp_port": 587,
            "smtp_user": "",
            "smtp_password": "",
            "alert_email_to": "",
            "alert_email_from": "",
        }
    )
    yield


class TestNotificationConfig:
    def test_env_fallback_when_db_empty(self, monkeypatch) -> None:
        monkeypatch.setenv("MIGRATION_WEBHOOK_URL", "https://example.com/hook")
        monkeypatch.setenv("MIGRATION_SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("MIGRATION_ALERT_EMAIL_TO", "dba@example.com")

        cfg = resolved_notification_config()
        assert cfg["webhook_configured"] is True
        assert cfg["email_configured"] is True
        assert cfg["source"] == "environment"

    def test_database_settings_take_precedence(self, monkeypatch) -> None:
        monkeypatch.setenv("MIGRATION_WEBHOOK_URL", "https://env.example/hook")
        set_settings(
            {
                "webhook_enabled": True,
                "webhook_url": encrypt_secret("https://db.example/hook"),
                "email_enabled": True,
                "smtp_host": "smtp.db.example",
                "smtp_port": 587,
                "smtp_user": "alerts@db.example",
                "smtp_password": encrypt_secret("secret"),
                "alert_email_to": "team@db.example",
                "alert_email_from": "alerts@db.example",
            }
        )

        cfg = resolved_notification_config()
        assert cfg["webhook_url"] == "https://db.example/hook"
        assert cfg["smtp_host"] == "smtp.db.example"
        assert cfg["alert_email_to"] == "team@db.example"
        assert cfg["source"] == "database"

    def test_status_masks_secrets(self) -> None:
        set_settings(
            {
                "webhook_enabled": True,
                "webhook_url": encrypt_secret("https://hooks.slack.com/services/ABCDEFG"),
                "email_enabled": True,
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "smtp_user": "alerts@example.com",
                "smtp_password": encrypt_secret("pw"),
                "alert_email_to": "dba@example.com",
                "alert_email_from": "alerts@example.com",
            }
        )

        status = notification_config_status()
        assert status["webhook_configured"] is True
        assert "hooks.slack" in status["webhook_url"]
        assert "•" in status["webhook_url"]
        assert status["smtp_password_set"] is True
        assert status["email_to"] == "dba@example.com"
