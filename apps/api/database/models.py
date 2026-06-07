"""Backward-compat shim — re-exports models from infrastructure/metadata_db/models.py.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from infrastructure.metadata_db.models import (
    Base,
    ConnectionRecord,
    MigrationJobRecord,
    MigrationTablePlanRecord,
    MigrationCommandRecord,
    ValidationRunRecord,
    ValidationMismatchRecord,
)

__all__ = [
    "Base",
    "ConnectionRecord",
    "MigrationJobRecord",
    "MigrationTablePlanRecord",
    "MigrationCommandRecord",
    "ValidationRunRecord",
    "ValidationMismatchRecord",
]
