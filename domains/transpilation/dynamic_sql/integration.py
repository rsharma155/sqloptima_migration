"""
Module: integration.py
Purpose: Backward-compatible helpers for dynamic SQL detection (pre-pass only).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from domains.transpilation.dynamic_sql.prepass import (
    apply_dynamic_sql_prepass,
    has_resolvable_dynamic_sql,
)

__all__ = [
    "apply_dynamic_sql_prepass",
    "has_resolvable_dynamic_sql",
]
