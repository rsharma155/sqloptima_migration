"""
Module: change_consumer.py
Purpose: Apply replicated changes to PostgreSQL with dedup and checkpointing
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from typing import Any

from apps.replicator.apply.applier import ChangeApplier
from apps.replicator.apply.checkpoint import CheckpointStore
from apps.replicator.apply.deduplicator import Deduplicator
from apps.replicator.capture.models import ChangeEvent
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


class ReplicationChangeConsumer:
    """Thin adapter around ChangeApplier for stream runtime integration."""

    def __init__(
        self,
        connection: Any,
        *,
        target_schema: str,
        table_pk_map: dict[str, list[str]] | None = None,
        redis_client: Any | None = None,
        dedup_capacity: int = 5000,
    ) -> None:
        self._target_schema = target_schema
        self._table_pk_map = {k.lower(): v for k, v in (table_pk_map or {}).items()}
        dedup = Deduplicator(redis_client=redis_client, max_size=dedup_capacity)
        checkpoint = CheckpointStore(connection)
        self._applier = ChangeApplier(connection, checkpoint, dedup)
        self.events_applied = 0

    async def handle(self, event: ChangeEvent) -> None:
        """Apply one change event to the target database."""
        event.table_schema = self._target_schema
        pk = self._table_pk_map.get(event.table_name.lower())
        applied = await self._applier.apply(event, pk_columns=pk)
        if applied:
            self.events_applied += 1
            logger.debug(
                "replication_event_applied",
                table=event.table_name,
                operation=event.operation.value,
            )
