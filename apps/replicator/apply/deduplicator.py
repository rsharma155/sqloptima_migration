"""
Module: apps/replicator/apply/deduplicator.py
Purpose: LSN-based dedup cache (in-memory LRU with optional Redis backend)
Author: Migration Platform Team
Created: 2026-05-22
Domain: Replication / Apply
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any

from apps.replicator.capture.models import LsnPosition

logger = logging.getLogger(__name__)


class Deduplicator:
    """Prevents duplicate application of change events.

    Uses an in-memory LRU cache keyed by ``(lsn_hex, qualified_table)``.
    An optional Redis backend provides persistence across restarts.

    The LRU eviction policy ensures bounded memory usage while keeping
    recently seen LSNs available for dedup.
    """

    def __init__(
        self,
        redis_client: Any | None = None,
        max_size: int = 100000,
        ttl_seconds: int = 3600,
    ) -> None:
        self._redis = redis_client
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._cache: OrderedDict[str, bool] = OrderedDict()

    async def already_applied(
        self, lsn: LsnPosition | str, qualified_table: str
    ) -> bool:
        """Check if an event with the given identity has already been applied.

        Args:
            lsn: The event's LSN position, or a pre-derived identity string
                (e.g. a synthetic :class:`~apps.replicator.apply.dedup_key.DedupKey`).
            qualified_table: ``schema.table`` identifier.

        Returns:
            True if the event was already applied.
        """
        key = self._make_key(lsn, qualified_table)
        if self._redis:
            val = await self._redis.get(key)
            return val is not None
        return key in self._cache

    async def record(self, lsn: LsnPosition | str, qualified_table: str) -> None:
        """Record that an event has been applied.

        Args:
            lsn: The event's LSN position, or a pre-derived identity string.
            qualified_table: ``schema.table`` identifier.
        """
        key = self._make_key(lsn, qualified_table)
        if self._redis:
            await self._redis.setex(key, self._ttl, b"1")
        else:
            self._cache[key] = True
            self._cache.move_to_end(key)
            if len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    async def clear(self) -> None:
        """Clear all dedup state using scoped key deletion."""
        if self._redis:
            cursor = 0
            pattern = "dedup:*"
            while True:
                cursor, keys = await self._redis.scan(cursor=cursor, match=pattern, count=100)
                if keys:
                    await self._redis.delete(*keys)
                if cursor == 0:
                    break
        self._cache.clear()

    def _make_key(self, lsn: LsnPosition | str, qualified_table: str) -> str:
        identity = lsn if isinstance(lsn, str) else lsn.to_string()
        return f"dedup:{identity}:{qualified_table}"
