"""
Module: apps/replicator/apply/dedup_key.py
Purpose: DedupKey — value object yielding a stable idempotency identity for a
         ChangeEvent. Uses the source LSN when present; otherwise derives a
         deterministic content-based synthetic key so events that arrive
         without an LSN can still be deduplicated exactly-once.
Domain: Replication / Apply
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT

Design notes:
    * ``ChangeEvent.event_id`` is a fresh random UUID per object and is therefore
      NOT a valid idempotency identity — the same logical row-change must hash
      identically across re-deliveries. The synthetic key is built from the
      change's *content* (operation, qualified table, identifying row values),
      never from the transient event_id.
    * This module owns identity derivation only. Cache storage/eviction is the
      Deduplicator's responsibility — keeping the two concerns decoupled.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from apps.replicator.capture.models import ChangeEvent, ChangeOperation

_SYNTHETIC_PREFIX = "syn:"


@dataclass(frozen=True)
class DedupKey:
    """An idempotency identity for a single change event.

    Attributes:
        value: The opaque key string used for deduplication.
        is_synthetic: True when the key was derived from row content because no
            authoritative LSN was available on the source event.
    """

    value: str
    is_synthetic: bool

    @classmethod
    def for_event(cls, event: ChangeEvent) -> DedupKey:
        """Derive the dedup identity for *event*.

        Prefers the source LSN; falls back to a deterministic content hash.
        """
        if event.lsn is not None:
            return cls(value=event.lsn.to_string(), is_synthetic=False)
        return cls(value=cls._synthesize(event), is_synthetic=True)

    @staticmethod
    def _identifying_values(event: ChangeEvent) -> dict:
        """Return the row values that identify this change.

        DELETE identity lives in ``before_values``; INSERT/UPDATE identity lives
        in ``after_values``. An empty dict is used when neither is present.
        """
        if event.operation == ChangeOperation.DELETE:
            return event.before_values or {}
        return event.after_values or event.before_values or {}

    @classmethod
    def _synthesize(cls, event: ChangeEvent) -> str:
        material = json.dumps(
            {
                "op": event.operation.value,
                "schema": event.table_schema,
                "table": event.table_name,
                "values": cls._identifying_values(event),
            },
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
        return f"{_SYNTHETIC_PREFIX}{digest}"

    def __str__(self) -> str:
        return self.value
