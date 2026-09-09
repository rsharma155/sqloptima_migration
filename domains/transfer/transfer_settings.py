"""
Module: transfer_settings.py
Purpose: Platform-level Transfer settings — file offload gates used by the data plane.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from typing import Any

DEFAULT_FILE_OFFLOAD_MIN_ROWS = 2_000_000
DEFAULT_FILE_OFFLOAD_MIN_MB = 256.0
MAX_STAGING_PATH_LEN = 1024
MAX_FILE_OFFLOAD_MIN_ROWS = 1_000_000_000
MAX_FILE_OFFLOAD_MIN_MB = 1_000_000.0


class TransferSettingsError(ValueError):
    """Invalid platform Transfer settings."""


def default_transfer_settings() -> dict[str, Any]:
    return {
        "file_offload_enabled": True,
        "file_offload_min_rows": DEFAULT_FILE_OFFLOAD_MIN_ROWS,
        "file_offload_min_mb": DEFAULT_FILE_OFFLOAD_MIN_MB,
        "staging_path": "",
    }


def default_file_offload() -> dict[str, Any]:
    settings = default_transfer_settings()
    return {
        "enabled": bool(settings["file_offload_enabled"]),
        "min_rows": int(settings["file_offload_min_rows"]),
        "min_mb": float(settings["file_offload_min_mb"]),
        "staging_path": str(settings["staging_path"]),
    }


def validate_transfer_settings(data: dict[str, Any] | None) -> dict[str, Any]:
    merged = {**default_transfer_settings(), **_normalize_file_offload_keys(data or {})}
    enabled = bool(merged.get("file_offload_enabled", True))
    try:
        min_rows = int(merged.get("file_offload_min_rows", DEFAULT_FILE_OFFLOAD_MIN_ROWS))
    except (TypeError, ValueError) as exc:
        raise TransferSettingsError("file_offload_min_rows must be an integer") from exc
    try:
        min_mb = float(merged.get("file_offload_min_mb", DEFAULT_FILE_OFFLOAD_MIN_MB))
    except (TypeError, ValueError) as exc:
        raise TransferSettingsError("file_offload_min_mb must be a number") from exc
    staging_path = str(merged.get("staging_path") or "").strip()
    if min_rows < 1 or min_rows > MAX_FILE_OFFLOAD_MIN_ROWS:
        raise TransferSettingsError(
            f"file_offload_min_rows must be between 1 and {MAX_FILE_OFFLOAD_MIN_ROWS}"
        )
    if min_mb <= 0 or min_mb > MAX_FILE_OFFLOAD_MIN_MB:
        raise TransferSettingsError(
            f"file_offload_min_mb must be greater than 0 and at most {MAX_FILE_OFFLOAD_MIN_MB}"
        )
    if len(staging_path) > MAX_STAGING_PATH_LEN:
        raise TransferSettingsError(
            f"staging_path must be at most {MAX_STAGING_PATH_LEN} characters"
        )
    return {
        "file_offload_enabled": enabled,
        "file_offload_min_rows": min_rows,
        "file_offload_min_mb": min_mb,
        "staging_path": staging_path,
    }


def _normalize_file_offload_keys(data: dict[str, Any]) -> dict[str, Any]:
    """Accept both platform keys and the compact dispatch snapshot keys."""
    out = dict(data)
    if "file_offload_enabled" not in out and "enabled" in out:
        out["file_offload_enabled"] = out["enabled"]
    if "file_offload_min_rows" not in out and "min_rows" in out:
        out["file_offload_min_rows"] = out["min_rows"]
    if "file_offload_min_mb" not in out and "min_mb" in out:
        out["file_offload_min_mb"] = out["min_mb"]
    return out


def file_offload_snapshot(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    validated = validate_transfer_settings(settings)
    return {
        "enabled": validated["file_offload_enabled"],
        "min_rows": validated["file_offload_min_rows"],
        "min_mb": validated["file_offload_min_mb"],
        "staging_path": validated["staging_path"],
    }


def should_file_offload(
    *,
    enabled: bool,
    min_rows: int,
    min_mb: float,
    row_estimate: int,
    size_mb: float,
    same_server: bool,
) -> bool:
    """Native BCP/BULK INSERT offload is cross-server only, and only above the app threshold."""
    if same_server or not enabled:
        return False
    if row_estimate >= min_rows:
        return True
    if size_mb > 0 and size_mb >= min_mb:
        return True
    return False
