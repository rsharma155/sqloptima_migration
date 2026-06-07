"""
Module: go_migration_status_mapper.py
Purpose: Map migration job status strings between Python control plane and Go engine.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from domains.migration.migration_engine import MigrationStatus

# Go engine uses uppercase constants in its binary; metadata DB stores lowercase.
_GO_TO_PYTHON: dict[str, MigrationStatus] = {
    "PENDING": MigrationStatus.PENDING,
    "QUEUED": MigrationStatus.QUEUED,
    "RUNNING": MigrationStatus.RUNNING,
    "PAUSED": MigrationStatus.PAUSED,
    "STOPPED": MigrationStatus.STOPPED,
    "COMPLETED": MigrationStatus.COMPLETED,
    "FAILED": MigrationStatus.FAILED,
    "RESUMED": MigrationStatus.RESUMED,
}

_PYTHON_TO_GO: dict[MigrationStatus, str] = {v: k for k, v in _GO_TO_PYTHON.items()}


def python_status_from_go(go_status: str) -> MigrationStatus:
    """Convert a Go engine status string to Python MigrationStatus."""
    normalized = go_status.strip().upper()
    if normalized not in _GO_TO_PYTHON:
        raise ValueError(f"Unknown Go migration status: {go_status!r}")
    return _GO_TO_PYTHON[normalized]


def go_status_from_python(status: MigrationStatus | str) -> str:
    """Convert Python MigrationStatus (or its value) to Go engine status string."""
    if isinstance(status, str):
        try:
            status = MigrationStatus(status.lower())
        except ValueError as exc:
            raise ValueError(f"Unknown Python migration status: {status!r}") from exc
    if status not in _PYTHON_TO_GO:
        raise ValueError(f"Unmapped Python migration status: {status!r}")
    return _PYTHON_TO_GO[status]
