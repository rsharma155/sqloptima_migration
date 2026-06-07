"""
Module: gateway.py
Purpose: Change data capture replication pipeline
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from apps.replicator.im.models import IMCommand


class IMGateway(ABC):
    @abstractmethod
    def send_message(self, chat_id: str, text: str) -> bool:
        ...

    @abstractmethod
    def send_markdown(self, chat_id: str, text: str) -> bool:
        ...

    @abstractmethod
    def start_polling(self, handler: Callable[[IMCommand], Awaitable[None]]) -> None:
        ...

    @abstractmethod
    def stop_polling(self) -> None:
        ...
