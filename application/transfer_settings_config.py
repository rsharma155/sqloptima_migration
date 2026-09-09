"""Resolve effective platform Transfer settings (DB-backed).

Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from typing import Any

from apps.api.transfer_settings_store import get_settings
from domains.transfer.transfer_settings import file_offload_snapshot, validate_transfer_settings


def resolved_file_offload() -> dict[str, Any]:
    return file_offload_snapshot(get_settings())


def transfer_settings_status() -> dict[str, Any]:
    stored = get_settings()
    validated = validate_transfer_settings(stored)
    return {
        **validated,
        "updated_at": stored.get("updated_at") or None,
    }
