"""
Module: replication_ports.py
Purpose: Hexagonal ports for replication control plane and messaging
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from typing import Any, Protocol

from apps.replicator.capture.models import ChangeEvent


class ChangePublisherPort(Protocol):
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def publish(self, event: ChangeEvent) -> bool: ...


class ChangeConsumerPort(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    @property
    def events_applied(self) -> int: ...


class ReplicationStreamRepositoryPort(Protocol):
    async def create(self, record: Any) -> Any: ...
    async def get(self, stream_id: str) -> Any | None: ...
    async def list_streams(self) -> list[Any]: ...
    async def update_status(
        self,
        stream_id: str,
        *,
        status: str,
        error_message: str | None = None,
        last_checkpoint_lsn: str | None = None,
        events_captured: int | None = None,
        events_applied: int | None = None,
    ) -> Any | None: ...
    async def delete(self, stream_id: str) -> bool: ...
