"""
Module: test_im_gateway.py
Purpose: Integration tests
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import pytest

from apps.replicator.im.command_parser import parse_message
from apps.replicator.im.models import IMCommand, UserRole
from apps.replicator.im.notifier import lag_alert, snapshot_complete
from apps.replicator.im.providers.dummy import DummyProvider


@pytest.fixture
def dummy():
    return DummyProvider(allowed_chat_ids=["admin_chat"])


@pytest.mark.asyncio
async def test_im_command_to_notification_flow(dummy):
    cmd = parse_message(
        "/start orders_cdc",
        source="telegram",
        chat_id="admin_chat",
        user_id="user_1",
        user_role=UserRole.ADMIN,
    )
    assert cmd.command == "start"
    assert cmd.args["config_id"] == "orders_cdc"

    notification = lag_alert("orders", 62.0, 30.0)
    result = dummy.send_markdown("admin_chat", notification)
    assert result is True
    assert dummy.message_count == 1
    _, chat, text = dummy.sent_messages[0]
    assert chat == "admin_chat"
    assert "62" in text
    assert "orders" in text


@pytest.mark.asyncio
async def test_parse_then_authorize_then_send(dummy):
    cmd = parse_message(
        "what is the status?",
        source="telegram",
        chat_id="admin_chat",
        user_id="user_1",
        user_role=UserRole.ADMIN,
    )
    assert cmd.command == "status"

    ok, msg = dummy.authorize(
        chat_id=cmd.chat_id,
        user_id=cmd.user_id,
        user_role=cmd.user_role,
    )
    assert ok is True, msg

    status_text = "Replication status: all jobs running"
    result = dummy.send_message(cmd.chat_id, status_text)
    assert result is True


@pytest.mark.asyncio
async def test_full_lifecycle_start_stop(dummy):
    cmd_start = parse_message("/start orders_sync")
    assert cmd_start.command == "start"

    ok, err = dummy.authorize(
        chat_id="admin_chat", user_id="op_1",
        user_role=UserRole.OPERATOR, required_role=UserRole.OPERATOR,
    )
    assert ok is True, err
    dummy.send_message("admin_chat", f"Started replication for {cmd_start.args['config_id']}")

    cmd_stop = parse_message("/stop orders_sync")
    assert cmd_stop.command == "stop"

    ok, err = dummy.authorize(
        chat_id="admin_chat", user_id="op_1",
        user_role=UserRole.OPERATOR, required_role=UserRole.OPERATOR,
    )
    assert ok is True, err
    dummy.send_message("admin_chat", f"Stopped replication for {cmd_stop.args['config_id']}")

    assert dummy.message_count == 2


@pytest.mark.asyncio
async def test_schedule_command_flow(dummy):
    cmd = parse_message('/schedule replicate --cron "*/5 * * * *"')
    assert cmd.command == "schedule"
    assert cmd.args["action"] == "replicate"
    assert cmd.args["cron"] == "*/5 * * * *"

    ok, err = dummy.authorize(
        chat_id="admin_chat", user_id="admin_1",
        user_role=UserRole.ADMIN, required_role=UserRole.ADMIN,
    )
    assert ok is True, err
    dummy.send_message("admin_chat", f"Schedule set: {cmd.args['cron']}")
    assert dummy.message_count == 1


@pytest.mark.asyncio
async def test_unauthorized_chat_rejected(dummy):
    cmd = parse_message(
        "/status",
        chat_id="unknown_chat",
        user_id="bad_user",
        user_role=UserRole.VIEWER,
    )
    ok, err = dummy.authorize(
        chat_id=cmd.chat_id,
        user_id=cmd.user_id,
        user_role=cmd.user_role,
    )
    assert ok is False
    assert "not allowed" in err


@pytest.mark.asyncio
async def test_notification_after_snapshot_complete(dummy):
    dummy.send_message("admin_chat", "Snapshot started for orders")
    notification = snapshot_complete("orders", 1200000, 34.0)
    dummy.send_markdown("admin_chat", notification)

    assert dummy.message_count == 2
    _, _, text = dummy.sent_messages[1]
    assert "snapshot complete" in text
    assert "1,200,000" in text


@pytest.mark.asyncio
async def test_polling_start_stop_handler(dummy):
    received: list[IMCommand] = []

    async def handler(cmd: IMCommand) -> None:
        received.append(cmd)

    dummy.start_polling(handler)
    assert dummy._handler is not None

    await handler(parse_message("/status"))
    await handler(parse_message("/help"))

    assert len(received) == 2
    assert received[0].command == "status"
    assert received[1].command == "help"

    dummy.stop_polling()
    assert dummy._handler is None
