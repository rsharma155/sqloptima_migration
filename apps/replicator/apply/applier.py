"""
Module: apps/replicator/apply/applier.py
Purpose: ChangeApplier — idempotent UPSERT, DELETE, and DDL application to PostgreSQL
Author: Migration Platform Team
Created: 2026-05-22
Domain: Replication / Apply
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import logging
from typing import Any

from apps.replicator.apply.checkpoint import CheckpointStore
from apps.replicator.apply.dedup_key import DedupKey
from apps.replicator.apply.deduplicator import Deduplicator
from apps.replicator.capture.models import ChangeEvent, ChangeOperation

logger = logging.getLogger(__name__)


def _quote_ident(name: str) -> str:
    """Quote a PostgreSQL identifier safely."""
    return f'"{name}"'


def _value_to_placeholder(idx: int) -> str:
    """Return a PostgreSQL positional placeholder ($1, $2, ...)."""
    return f"${idx}"


class ChangeApplier:
    """Applies ChangeEvents to the target PostgreSQL database.

    Uses idempotent UPSERT for INSERT/UPDATE and standard DELETE.
    Checks the deduplicator before each apply to ensure exactly-once semantics.
    """

    def __init__(
        self,
        connection: Any,
        checkpoint_store: CheckpointStore,
        deduplicator: Deduplicator,
    ) -> None:
        self._conn = connection
        self._checkpoint = checkpoint_store
        self._dedup = deduplicator
        self.stats: dict[str, int] = {
            "applied": 0,
            "duplicate": 0,
            "insert": 0,
            "update": 0,
            "delete": 0,
            "failed": 0,
        }
        self.recent_errors: list[str] = []

    async def apply(self, event: ChangeEvent, pk_columns: list[str] | None = None) -> bool:
        """Apply a single change event to the target database.

        Args:
            event: Change event to apply.
            pk_columns: Primary key columns (auto-detected from after_values keys if omitted).

        Returns:
            True if applied successfully or already applied.
        """
        qualified = f"{event.table_schema}.{event.table_name}"

        # Always derive a dedup identity — LSN when present, else a
        # deterministic content-based synthetic key (Issue #4). This closes the
        # exactly-once gap for providers that deliver events without an LSN.
        dedup_key = DedupKey.for_event(event)
        if await self._dedup.already_applied(dedup_key.value, qualified):
            logger.debug("Skipping duplicate event %s for %s", dedup_key.value, qualified)
            self.stats["duplicate"] += 1
            return True

        try:
            if event.operation == ChangeOperation.DELETE:
                sql, params = self._build_delete(
                    event, pk_columns or list(event.before_values or {}),
                )
            else:
                sql, params = self._build_upsert(event, pk_columns or self._detect_pk(event))

            await self._conn.execute(sql, params)
        except Exception as exc:
            self.stats["failed"] += 1
            msg = f"{qualified} {event.operation.value}: {exc}"
            self.recent_errors.append(msg)
            if len(self.recent_errors) > 20:
                self.recent_errors.pop(0)
            raise

        await self._dedup.record(dedup_key.value, qualified)
        self.stats["applied"] += 1
        op_key = event.operation.value.lower()
        if op_key in self.stats:
            self.stats[op_key] += 1
        # Checkpoints track LSN-based resume position; only meaningful when the
        # source supplied an authoritative LSN.
        if event.lsn:
            await self._checkpoint.save(event.table_schema, event.table_name, event.lsn)

        return True

    async def apply_batch(
        self,
        events: list[ChangeEvent],
        pk_columns: list[str] | None = None,
    ) -> list[bool]:
        """Apply a batch of change events inside a single atomic transaction.

        Fix 2.3: wrapping in a transaction ensures partial-apply is impossible.
        If any event raises, the entire batch is rolled back.

        Args:
            events: List of change events.
            pk_columns: Primary key columns forwarded to each apply() call.

        Returns:
            List of booleans indicating success per event.
        """
        if not events:
            return []
        async with self._conn.transaction():
            results: list[bool] = []
            for event in events:
                results.append(await self.apply(event, pk_columns))
            return results

    @staticmethod
    def _detect_pk(event: ChangeEvent) -> list[str]:
        """Detect primary key columns from after_values.

        Assumes the first column is the PK if no explicit PK is provided.
        """
        vals = event.after_values or event.before_values or {}
        keys = list(vals.keys())
        return [keys[0]] if keys else ["id"]

    @staticmethod
    def _build_upsert(event: ChangeEvent, pk_columns: list[str]) -> tuple[str, dict]:
        """Build an idempotent UPSERT (INSERT ... ON CONFLICT DO UPDATE).

        Args:
            event: Change event with after_values.
            pk_columns: Primary key column names.

        Returns:
            Tuple of (PostgreSQL UPSERT SQL string, params dict).
        """
        values = event.after_values or {}
        if not values:
            return "", {}

        cols = list(values.keys())
        quoted_cols = ", ".join(_quote_ident(c) for c in cols)

        params = {}
        placeholders = ", ".join(
            _value_to_placeholder(i) for i in range(1, len(cols) + 1)
        )
        for idx, c in enumerate(cols, 1):
            params[str(idx)] = values[c]

        updates = ", ".join(
            f"{_quote_ident(c)} = EXCLUDED.{_quote_ident(c)}" for c in cols
        )

        conflict_cols = ", ".join(_quote_ident(c) for c in pk_columns)

        qualified = f"{_quote_ident(event.table_schema)}.{_quote_ident(event.table_name)}"

        return (
            f"INSERT INTO {qualified} ({quoted_cols})\n"
            f"VALUES ({placeholders})\n"
            f"ON CONFLICT ({conflict_cols})\n"
            f"DO UPDATE SET {updates};",
            params,
        )

    @staticmethod
    def _build_delete(event: ChangeEvent, pk_columns: list[str]) -> tuple[str, dict]:
        """Build a DELETE statement for the given event.

        Args:
            event: Change event with before_values containing PK values.
            pk_columns: Primary key column names.

        Returns:
            Tuple of (PostgreSQL DELETE SQL string, params dict).
        """
        before = event.before_values or {}
        params = {}
        cond_parts = []
        for idx, c in enumerate(pk_columns, 1):
            cond_parts.append(f"{_quote_ident(c)} = ${idx}")
            params[str(idx)] = before.get(c)
        conditions = " AND ".join(cond_parts)
        qualified = f"{_quote_ident(event.table_schema)}.{_quote_ident(event.table_name)}"

        return f"DELETE FROM {qualified}\nWHERE {conditions};", params
