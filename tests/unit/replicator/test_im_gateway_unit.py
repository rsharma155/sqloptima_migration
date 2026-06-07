"""
Module: test_im_gateway_unit.py
Purpose: Unit tests
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.replicator.im.command_parser import parse_message
from apps.replicator.im.models import IMCommand, IMProviderConfig, UserRole
from apps.replicator.im.notifier import (
    consumer_error,
    heartbeat,
    lag_alert,
    schema_drift_detected,
    snapshot_complete,
)
from apps.replicator.im.providers.dummy import DummyProvider


@pytest.fixture
def dummy_provider():
    return DummyProvider(allowed_chat_ids=["chat_1", "chat_2"])


class TestDummyProviderSend:
    def test_send_message_dummy(self, dummy_provider):
        result = dummy_provider.send_message("chat_1", "Hello")
        assert result is True
        assert len(dummy_provider.sent_messages) == 1
        msg_type, chat, text = dummy_provider.sent_messages[0]
        assert msg_type == "text"
        assert chat == "chat_1"
        assert text == "Hello"

    def test_send_markdown_dummy(self, dummy_provider):
        result = dummy_provider.send_markdown("chat_2", "**bold**")
        assert result is True
        assert len(dummy_provider.sent_messages) == 1
        msg_type, chat, text = dummy_provider.sent_messages[0]
        assert msg_type == "markdown"
        assert chat == "chat_2"
        assert text == "**bold**"

    def test_clear_messages(self, dummy_provider):
        dummy_provider.send_message("chat_1", "one")
        dummy_provider.send_message("chat_1", "two")
        assert dummy_provider.message_count == 2
        dummy_provider.clear_messages()
        assert dummy_provider.message_count == 0


class TestRateLimiting:
    def test_rate_limiting(self):
        provider = DummyProvider(rate_limit=3, rate_window=60.0)
        for _ in range(3):
            assert provider.check_rate_limit("user_1") is True
        assert provider.check_rate_limit("user_1") is False

    def test_rate_limit_per_user(self):
        provider = DummyProvider(rate_limit=2, rate_window=60.0)
        assert provider.check_rate_limit("user_a") is True
        assert provider.check_rate_limit("user_a") is True
        assert provider.check_rate_limit("user_a") is False
        assert provider.check_rate_limit("user_b") is True


class TestAuthorization:
    def test_allowlist_allows_known_chat(self, dummy_provider):
        ok, msg = dummy_provider.authorize(chat_id="chat_1", user_id="u1")
        assert ok is True
        assert msg == ""

    def test_allowlist_rejects_unknown_chat(self, dummy_provider):
        ok, msg = dummy_provider.authorize(chat_id="chat_unknown", user_id="u1")
        assert ok is False
        assert "not allowed" in msg

    def test_allowlist_empty_allows_all(self):
        provider = DummyProvider()
        ok, msg = provider.authorize(chat_id="anything", user_id="u1")
        assert ok is True

    def test_role_check_admin(self, dummy_provider):
        ok, msg = dummy_provider.authorize(
            chat_id="chat_1", user_id="u1",
            user_role=UserRole.ADMIN, required_role=UserRole.ADMIN,
        )
        assert ok is True

    def test_role_check_operator(self, dummy_provider):
        ok, msg = dummy_provider.authorize(
            chat_id="chat_1", user_id="u1",
            user_role=UserRole.OPERATOR, required_role=UserRole.ADMIN,
        )
        assert ok is False
        assert "Insufficient role" in msg

    def test_role_check_viewer(self, dummy_provider):
        ok, msg = dummy_provider.authorize(
            chat_id="chat_1", user_id="u1",
            user_role=UserRole.VIEWER, required_role=UserRole.VIEWER,
        )
        assert ok is True


class TestCommandParser:
    def test_command_parser_status(self):
        cmd = parse_message("/status")
        assert cmd.command == "status"
        assert cmd.args == {}

    def test_command_parser_start(self):
        cmd = parse_message("/start job_42")
        assert cmd.command == "start"
        assert cmd.args == {"config_id": "job_42"}

    def test_command_parser_stop(self):
        cmd = parse_message("/stop job_42")
        assert cmd.command == "stop"
        assert cmd.args == {"config_id": "job_42"}

    def test_command_parser_pause(self):
        cmd = parse_message("/pause job_42")
        assert cmd.command == "pause"
        assert cmd.args == {"config_id": "job_42"}

    def test_command_parser_resume(self):
        cmd = parse_message("/resume job_42")
        assert cmd.command == "resume"
        assert cmd.args == {"config_id": "job_42"}

    def test_command_parser_schedule(self):
        cmd = parse_message('/schedule replicate --cron "*/5 * * * *"')
        assert cmd.command == "schedule"
        assert cmd.args == {"action": "replicate", "cron": "*/5 * * * *"}

    def test_command_parser_help(self):
        cmd = parse_message("/help")
        assert cmd.command == "help"

    def test_command_parser_natural_language_status(self):
        cmd = parse_message("what is the status?")
        assert cmd.command == "status"

    def test_command_parser_natural_language_start(self):
        cmd = parse_message("start replication for orders")
        assert cmd.command == "start"
        assert "config_id" in cmd.args

    def test_command_parser_invalid(self):
        cmd = parse_message("/foobar baz")
        assert cmd.command == "unknown"
        assert cmd.args == {}

    def test_command_parser_natural_language_no_match(self):
        cmd = parse_message("hello world how are you")
        assert cmd.command == "unknown"

    def test_command_parser_sets_metadata(self):
        cmd = parse_message(
            "/status",
            source="telegram",
            chat_id="chat_99",
            user_id="user_abc",
            user_role=UserRole.VIEWER,
        )
        assert cmd.source == "telegram"
        assert cmd.chat_id == "chat_99"
        assert cmd.user_id == "user_abc"
        assert cmd.user_role == UserRole.VIEWER
        assert isinstance(cmd.timestamp, datetime)
        assert cmd.timestamp.tzinfo is UTC


class TestNotifier:
    def test_notifier_lag_alert(self):
        msg = lag_alert("orders", 62.0, 30.0)
        assert "orders" in msg
        assert "62" in msg
        assert "30" in msg
        assert "\U0001f6a8" in msg

    def test_notifier_snapshot_complete(self):
        msg = snapshot_complete("orders", 1200000, 34.0)
        assert "orders" in msg
        assert "1,200,000" in msg
        assert "34" in msg
        assert "\u2705" in msg

    def test_notifier_schema_drift(self):
        changes = [
            {"type": "column_added", "column": "discount_pct"},
            {"type": "type_changed", "column": "total"},
        ]
        msg = schema_drift_detected("orders", changes)
        assert "orders" in msg
        assert "discount_pct" in msg
        assert "total" in msg
        assert "\u26a0\ufe0f" in msg

    def test_notifier_consumer_error(self):
        msg = consumer_error("orders", 3, 5)
        assert "orders" in msg
        assert "3" in msg
        assert "5" in msg
        assert "\U0001f6a8" in msg

    def test_notifier_heartbeat(self):
        info = {"service": "replicator", "status": "healthy"}
        msg = heartbeat(info)
        assert "replicator" in msg
        assert "healthy" in msg
        assert "\u2139\ufe0f" in msg


class TestIMProviderConfig:
    def test_provider_config_defaults(self):
        cfg = IMProviderConfig(provider_type="telegram")
        assert cfg.provider_type == "telegram"
        assert cfg.api_key == ""
        assert cfg.allowed_chat_ids == []
        assert cfg.enabled is True

    def test_provider_config_custom(self):
        cfg = IMProviderConfig(
            provider_type="slack",
            api_key="xoxb-secret",
            allowed_chat_ids=["C001", "C002"],
            enabled=False,
        )
        assert cfg.api_key == "xoxb-secret"
        assert cfg.allowed_chat_ids == ["C001", "C002"]
        assert cfg.enabled is False


class TestIMCommand:
    def test_imcommand_defaults(self):
        cmd = IMCommand(
            source="test", chat_id="c1", user_id="u1",
            user_role=UserRole.ADMIN, command="status",
        )
        assert cmd.args == {}
        assert cmd.raw_text == ""
        assert isinstance(cmd.timestamp, datetime)

    def test_imcommand_full(self):
        cmd = IMCommand(
            source="telegram",
            chat_id="c1",
            user_id="u1",
            user_role=UserRole.OPERATOR,
            command="start",
            args={"config_id": "job_1"},
            raw_text="/start job_1",
        )
        assert cmd.args["config_id"] == "job_1"
        assert cmd.raw_text == "/start job_1"


class TestGatewayMultipleProviders:
    def test_gateway_multiple_providers(self):
        p1 = DummyProvider(allowed_chat_ids=["chat_a"])
        p2 = DummyProvider(allowed_chat_ids=["chat_b"])

        p1.send_message("chat_a", "msg from p1")
        p2.send_message("chat_b", "msg from p2")

        assert p1.message_count == 1
        assert p2.message_count == 1
        assert p1.sent_messages[0][2] == "msg from p1"
        assert p2.sent_messages[0][2] == "msg from p2"

    def test_provider_independent_chat_lists(self):
        p1 = DummyProvider(allowed_chat_ids=["chat_1"])
        p2 = DummyProvider(allowed_chat_ids=["chat_2"])

        ok1, _ = p1.authorize(chat_id="chat_1", user_id="u1")
        ok2, _ = p2.authorize(chat_id="chat_1", user_id="u1")

        assert ok1 is True
        assert ok2 is False

    def test_provider_independent_rate_limits(self):
        p1 = DummyProvider(rate_limit=1, rate_window=60.0)
        p2 = DummyProvider(rate_limit=5, rate_window=60.0)

        assert p1.check_rate_limit("user_x") is True
        assert p1.check_rate_limit("user_x") is False
        for _ in range(5):
            assert p2.check_rate_limit("user_x") is True
        assert p2.check_rate_limit("user_x") is False
