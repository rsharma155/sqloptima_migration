"""
Module: dummy.py
Purpose: Change data capture replication pipeline
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable

from apps.replicator.im.models import IMCommand
from apps.replicator.im.providers.provider_base import ProviderBase

logger = logging.getLogger(__name__)


class DummyProvider(ProviderBase):
    def __init__(
        self,
        allowed_chat_ids: list[str] | None = None,
        rate_limit: int = 10,
        rate_window: float = 60.0,
    ) -> None:
        super().__init__(
            allowed_chat_ids=allowed_chat_ids,
            rate_limit=rate_limit,
            rate_window=rate_window,
        )
        self.sent_messages: deque[tuple[str, str, str]] = deque()
        self._polling = False
        self._poll_task: asyncio.Task[None] | None = None

    def send_message(self, chat_id: str, text: str) -> bool:
        self.sent_messages.append(("text", chat_id, text))
        logger.info("[DummyProvider] Sending text to %s: %s", chat_id, text)
        print(f"[DummyProvider] text -> {chat_id}: {text}")
        return True

    def send_markdown(self, chat_id: str, text: str) -> bool:
        self.sent_messages.append(("markdown", chat_id, text))
        logger.info("[DummyProvider] Sending markdown to %s: %s", chat_id, text)
        print(f"[DummyProvider] markdown -> {chat_id}: {text}")
        return True

    def start_polling(self, handler: Callable[[IMCommand], Awaitable[None]]) -> None:
        self._handler = handler
        self._polling = True
        logger.info("[DummyProvider] Polling started (simulated)")

    def stop_polling(self) -> None:
        self._polling = False
        if self._poll_task:
            self._poll_task.cancel()
        self._handler = None
        logger.info("[DummyProvider] Polling stopped")

    @property
    def message_count(self) -> int:
        return len(self.sent_messages)

    def clear_messages(self) -> None:
        self.sent_messages.clear()
