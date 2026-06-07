"""
Module: command_parser.py
Purpose: Change data capture replication pipeline
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from apps.replicator.im.models import IMCommand, UserRole

_COMMAND_PATTERNS: list[tuple[re.Pattern[str], str, list[str]]] = [
    (re.compile(r"^/status\s*$", re.IGNORECASE), "status", []),
    (re.compile(r"^/start\s+(.+)$", re.IGNORECASE), "start", ["config_id"]),
    (re.compile(r"^/stop\s+(.+)$", re.IGNORECASE), "stop", ["config_id"]),
    (re.compile(r"^/pause\s+(.+)$", re.IGNORECASE), "pause", ["config_id"]),
    (re.compile(r"^/resume\s+(.+)$", re.IGNORECASE), "resume", ["config_id"]),
    (re.compile(r"^/schedule\s+(\w+)\s+--cron\s+\"([^\"]+)\"$", re.IGNORECASE), "schedule", ["action", "cron"]),  # noqa: E501
    (re.compile(r"^/help\s*$", re.IGNORECASE), "help", []),
]

_NL_PATTERNS: list[tuple[re.Pattern[str], str, dict[str, Any]]] = [
    (re.compile(r"(?:what\s+is\s+)?(?:the\s+)?status", re.IGNORECASE), "status", {}),
    (re.compile(r"start\s+replication\s+for\s+(\w+)", re.IGNORECASE), "start", {}),
    (re.compile(r"stop\s+replication\s+for\s+(\w+)", re.IGNORECASE), "stop", {}),
    (re.compile(r"pause\s+replication\s+for\s+(\w+)", re.IGNORECASE), "pause", {}),
    (re.compile(r"resume\s+replication\s+for\s+(\w+)", re.IGNORECASE), "resume", {}),
]


def parse_message(
    text: str,
    source: str = "test",
    chat_id: str = "default",
    user_id: str = "default",
    user_role: UserRole = UserRole.ADMIN,
) -> IMCommand:
    text_stripped = text.strip()

    for pattern, command, param_names in _COMMAND_PATTERNS:
        match = pattern.match(text_stripped)
        if match:
            groups = match.groups()
            args: dict[str, Any] = {}
            if command == "schedule":
                args = {"action": groups[0], "cron": groups[1]}
            elif param_names:
                args = {param_names[0]: groups[0]}
            return IMCommand(
                source=source,
                chat_id=chat_id,
                user_id=user_id,
                user_role=user_role,
                command=command,
                args=args,
                raw_text=text_stripped,
                timestamp=datetime.now(UTC),
            )

    for pattern, command, extra_args in _NL_PATTERNS:
        match = pattern.search(text_stripped)
        if match:
            groups = match.groups()
            args = dict(extra_args)
            if groups:
                args["config_id"] = groups[0]
            return IMCommand(
                source=source,
                chat_id=chat_id,
                user_id=user_id,
                user_role=user_role,
                command=command,
                args=args,
                raw_text=text_stripped,
                timestamp=datetime.now(UTC),
            )

    return IMCommand(
        source=source,
        chat_id=chat_id,
        user_id=user_id,
        user_role=user_role,
        command="unknown",
        args={},
        raw_text=text_stripped,
        timestamp=datetime.now(UTC),
    )
