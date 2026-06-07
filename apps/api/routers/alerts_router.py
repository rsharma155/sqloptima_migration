"""Platform alerts and notification configuration routes.

Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel

from application.alert_service import AlertService, notification_config_status
from application.notification_service import NotificationService
from apps.api.middleware.auth import UserRole, require_role
from shared.tenancy.project_scope import resolve_project_filter

router = APIRouter(prefix="/alerts", tags=["alerts"])


class TestAlertRequest(BaseModel):
    channel: str = "all"  # webhook | email | all


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


@router.post("/test")
async def test_alert_channels(
    req: TestAlertRequest,
    _: dict = require_role(UserRole.ADMIN),
):
    notifier = NotificationService()
    results = await notifier.send_test_alert(req.channel)
    return {"results": results}
