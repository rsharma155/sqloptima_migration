"""Resolve effective platform replication capture settings (DB-backed).

Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.api.replication_settings_store import get_settings


@dataclass(frozen=True)
class ReplicationCaptureSettings:
    poll_interval_ms: int = 1000
    batch_size: int = 1000


def resolved_replication_capture_settings() -> ReplicationCaptureSettings:
    stored = get_settings()
    return ReplicationCaptureSettings(
        poll_interval_ms=int(stored.get("poll_interval_ms", 1000)),
        batch_size=int(stored.get("batch_size", 1000)),
    )


def replication_settings_status() -> dict[str, Any]:
    stored = get_settings()
    capture = resolved_replication_capture_settings()
    return {
        "poll_interval_ms": capture.poll_interval_ms,
        "poll_interval_sec": capture.poll_interval_ms / 1000.0,
        "batch_size": capture.batch_size,
        "updated_at": stored.get("updated_at") or None,
    }
