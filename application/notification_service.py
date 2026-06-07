"""NotificationService — webhook and optional SMTP email alerts on migration lifecycle events.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import asyncio
import json
import os
import smtplib
from email.message import EmailMessage
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


class NotificationService:
    def __init__(
        self,
        webhook_url: str | None = None,
        *,
        smtp_host: str | None = None,
        smtp_port: int | None = None,
        smtp_user: str | None = None,
        smtp_password: str | None = None,
        alert_email_to: str | None = None,
        alert_email_from: str | None = None,
    ) -> None:
        self._webhook_url = webhook_url or os.environ.get("MIGRATION_WEBHOOK_URL")
        self._smtp_host = smtp_host or os.environ.get("MIGRATION_SMTP_HOST")
        self._smtp_port = smtp_port or int(os.environ.get("MIGRATION_SMTP_PORT", "587"))
        self._smtp_user = smtp_user or os.environ.get("MIGRATION_SMTP_USER")
        self._smtp_password = smtp_password or os.environ.get("MIGRATION_SMTP_PASSWORD")
        self._alert_email_to = alert_email_to or os.environ.get("MIGRATION_ALERT_EMAIL_TO")
        self._alert_email_from = (
            alert_email_from
            or os.environ.get("MIGRATION_ALERT_EMAIL_FROM")
            or self._smtp_user
            or "alerts@sql-optima.local"
        )

    @property
    def email_configured(self) -> bool:
        return bool(self._smtp_host and self._alert_email_to)

    async def notify(self, event_name: str, payload: dict[str, Any]) -> None:
        body = {"event": event_name, **payload}
        await self._send_webhook(event_name, body)
        await self._send_email(event_name, body)

    async def _send_webhook(self, event_name: str, body: dict[str, Any]) -> None:
        if not self._webhook_url:
            logger.debug("notification_skipped_no_webhook", notification_event=event_name)
            return
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._post_webhook_sync, body)
            logger.info("notification_sent", notification_event=event_name, channel="webhook")
        except Exception as exc:
            logger.warning(
                "notification_failed",
                notification_event=event_name,
                channel="webhook",
                error=str(exc),
            )

    def _post_webhook_sync(self, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        req = Request(
            self._webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=10) as resp:  # noqa: S310 — operator-configured webhook URL
            if resp.status >= 400:
                raise URLError(f"Webhook returned HTTP {resp.status}")

    async def _send_email(self, event_name: str, body: dict[str, Any]) -> None:
        if not self.email_configured:
            logger.debug("notification_skipped_no_email", notification_event=event_name)
            return
        subject = f"[SQL Optima] {event_name}"
        text = json.dumps(body, indent=2)
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._send_email_sync, subject, text)
            logger.info("notification_sent", notification_event=event_name, channel="email")
        except Exception as exc:
            logger.warning(
                "notification_failed",
                notification_event=event_name,
                channel="email",
                error=str(exc),
            )

    def _send_email_sync(self, subject: str, text: str) -> None:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self._alert_email_from
        msg["To"] = self._alert_email_to
        msg.set_content(text)
        with smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=15) as smtp:
            smtp.starttls()
            if self._smtp_user and self._smtp_password:
                smtp.login(self._smtp_user, self._smtp_password)
            smtp.send_message(msg)

    async def job_started(self, job_id: str, tables: list[str]) -> None:
        await self.notify("migration.started", {"job_id": job_id, "tables": tables})

    async def job_completed(self, job_id: str, status: str, rows_migrated: int = 0) -> None:
        await self.notify(
            "migration.completed",
            {"job_id": job_id, "status": status, "rows_migrated": rows_migrated},
        )

    async def job_failed(self, job_id: str, error: str) -> None:
        await self.notify("migration.failed", {"job_id": job_id, "error": error})

    async def send_test_alert(self, channel: str = "all") -> dict[str, str]:
        payload = {
            "event": "alert.test",
            "message": "SQL Optima test alert — channels are configured correctly.",
        }
        results: dict[str, str] = {}
        if channel in ("webhook", "all"):
            if not self._webhook_url:
                results["webhook"] = "skipped — MIGRATION_WEBHOOK_URL not set"
            else:
                try:
                    await self._send_webhook("alert.test", payload)
                    results["webhook"] = "sent"
                except Exception as exc:
                    results["webhook"] = f"failed: {exc}"
        if channel in ("email", "all"):
            if not self.email_configured:
                results["email"] = (
                    "skipped — set MIGRATION_SMTP_HOST and MIGRATION_ALERT_EMAIL_TO"
                )
            else:
                try:
                    await self._send_email("alert.test", payload)
                    results["email"] = "sent"
                except Exception as exc:
                    results["email"] = f"failed: {exc}"
        return results
