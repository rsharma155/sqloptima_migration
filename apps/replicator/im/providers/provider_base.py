"""
Module: provider_base.py
Purpose: Change data capture replication pipeline
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from apps.replicator.im.gateway import IMGateway
from apps.replicator.im.models import IMCommand, UserRole

logger = logging.getLogger(__name__)


class TokenBucket:
    def __init__(self, rate: int = 10, per_seconds: float = 60.0) -> None:
        self.rate = rate
        self.per_seconds = per_seconds
        self.tokens: dict[str, float] = defaultdict(lambda: float(rate))
        self.last_refill: dict[str, float] = defaultdict(float)

    def consume(self, key: str) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill[key]
        self.tokens[key] = min(
            float(self.rate), self.tokens[key] + elapsed * self.rate / self.per_seconds,
        )
        self.last_refill[key] = now
        if self.tokens[key] >= 1.0:
            self.tokens[key] -= 1.0
            return True
        return False


class ProviderBase(IMGateway):
    def __init__(
        self,
        allowed_chat_ids: list[str] | None = None,
        rate_limit: int = 10,
        rate_window: float = 60.0,
    ) -> None:
        self._allowed_chat_ids: set[str] = set(allowed_chat_ids or [])
        self._bucket = TokenBucket(rate=rate_limit, per_seconds=rate_window)
        self._handler: Callable[[IMCommand], Awaitable[None]] | None = None

    def is_chat_allowed(self, chat_id: str) -> bool:
        if not self._allowed_chat_ids:
            return True
        return chat_id in self._allowed_chat_ids

    def check_rate_limit(self, user_id: str) -> bool:
        return self._bucket.consume(user_id)

    def check_role(self, user_role: UserRole, required_role: UserRole = UserRole.VIEWER) -> bool:
        role_order = {UserRole.VIEWER: 0, UserRole.OPERATOR: 1, UserRole.ADMIN: 2}
        return role_order.get(user_role, -1) >= role_order.get(required_role, 0)

    def authorize(
        self,
        chat_id: str,
        user_id: str,
        user_role: UserRole = UserRole.VIEWER,
        required_role: UserRole = UserRole.VIEWER,
    ) -> tuple[bool, str]:
        if not self.is_chat_allowed(chat_id):
            return False, "Chat ID not allowed"
        if not self.check_rate_limit(user_id):
            return False, "Rate limit exceeded"
        if not self.check_role(user_role, required_role):
            return False, f"Insufficient role (need {required_role.value})"
        return True, ""

    def send_message(self, chat_id: str, text: str) -> bool:
        raise NotImplementedError

    def send_markdown(self, chat_id: str, text: str) -> bool:
        raise NotImplementedError

    def start_polling(self, handler: Callable[[IMCommand], Awaitable[None]]) -> None:
        self._handler = handler

    def stop_polling(self) -> None:
        self._handler = None

    def _build_command(
        self,
        source: str,
        chat_id: str,
        user_id: str,
        user_role: UserRole,
        command: str,
        args: dict[str, Any] | None = None,
        raw_text: str = "",
    ) -> IMCommand:
        return IMCommand(
            source=source,
            chat_id=chat_id,
            user_id=user_id,
            user_role=user_role,
            command=command,
            args=args or {},
            raw_text=raw_text,
        )
