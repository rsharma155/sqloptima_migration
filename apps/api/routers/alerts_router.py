"""Platform alerts and notification configuration routes.

Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from application.alert_service import AlertService
from application.notification_config import notification_config_status
from application.notification_service import create_notification_service
from apps.api.middleware.auth import UserRole, require_role
from apps.api.notification_settings_store import (
    encrypt_secret,
    get_settings,
    save_settings_async,
    set_settings,
)
from shared.tenancy.project_scope import resolve_project_filter

router = APIRouter(prefix="/alerts", tags=["alerts"])


class TestAlertRequest(BaseModel):
    channel: str = "all"  # webhook | email | all


class NotificationSettingsUpdate(BaseModel):
    webhook_enabled: bool = False
    webhook_url: str = ""
    email_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: str = ""
    smtp_password: str = ""
    alert_email_to: str = ""
    alert_email_from: str = ""


@router.get("")
async def list_alerts(
    project_id: str | None = Query(default=None),
    user: dict = require_role(UserRole.VIEWER),
):
    scope = resolve_project_filter(
        project_id,
        user_project_id=user.get("project_id"),
        is_admin=user.get("role") == UserRole.ADMIN.value,
    )
    svc = AlertService()
    alerts = svc.collect(project_id=scope)
    return {
        "alerts": [a.to_dict() for a in alerts],
        "summary": svc.summary(alerts),
        "checked_at": datetime.now(UTC).isoformat(),
    }


@router.get("/config")
async def get_alert_config(_: dict = require_role(UserRole.VIEWER)):
    return notification_config_status()


@router.put("/config")
async def update_alert_config(
    req: NotificationSettingsUpdate,
    _: dict = require_role(UserRole.ADMIN),
):
    existing = get_settings()

    if req.webhook_enabled and not req.webhook_url.strip() and not existing.get("webhook_url"):
        raise HTTPException(status_code=400, detail="Webhook URL is required when webhook alerts are enabled")

    if req.email_enabled:
        if not req.smtp_host.strip():
            raise HTTPException(status_code=400, detail="SMTP host is required when email alerts are enabled")
        if not req.alert_email_to.strip():
            raise HTTPException(status_code=400, detail="Alert recipient email is required when email alerts are enabled")

    webhook_secret = existing.get("webhook_url", "")
    if req.webhook_url.strip():
        webhook_secret = encrypt_secret(req.webhook_url.strip())

    smtp_password = existing.get("smtp_password", "")
    if req.smtp_password:
        smtp_password = encrypt_secret(req.smtp_password)

    set_settings(
        {
            "webhook_enabled": req.webhook_enabled,
            "webhook_url": webhook_secret if req.webhook_enabled else "",
            "email_enabled": req.email_enabled,
            "smtp_host": req.smtp_host.strip() if req.email_enabled else "",
            "smtp_port": req.smtp_port,
            "smtp_user": req.smtp_user.strip() if req.email_enabled else "",
            "smtp_password": smtp_password if req.email_enabled else "",
            "alert_email_to": req.alert_email_to.strip() if req.email_enabled else "",
            "alert_email_from": req.alert_email_from.strip() if req.email_enabled else "",
        }
    )
    await save_settings_async()
    return notification_config_status()


@router.post("/test")
async def test_alert_channels(
    req: TestAlertRequest,
    _: dict = require_role(UserRole.ADMIN),
):
    notifier = create_notification_service()
    results = await notifier.send_test_alert(req.channel)
    return {"results": results}
