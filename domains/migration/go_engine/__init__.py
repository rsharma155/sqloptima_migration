"""
Module: domains/migration/go_engine
Purpose: Domain types for Go data-plane job dispatch (control → data plane contract).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from domains.migration.go_engine.go_connection_dispatch_ref import GoConnectionDispatchRef
from domains.migration.go_engine.go_executor_kind import GoExecutorKind
from domains.migration.go_engine.go_job_dispatch_config import GoJobDispatchConfig
from domains.migration.go_engine.go_migration_status_mapper import (
    go_status_from_python,
    python_status_from_go,
)
from domains.migration.go_engine.go_table_dispatch_payload import GoTableDispatchPayload

__all__ = [
    "GoConnectionDispatchRef",
    "GoExecutorKind",
    "GoJobDispatchConfig",
    "GoTableDispatchPayload",
    "go_status_from_python",
    "python_status_from_go",
]
