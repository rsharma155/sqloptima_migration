"""
Module: go_executor_kind.py
Purpose: Identifies which runtime executes migration data movement.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from enum import StrEnum


class GoExecutorKind(StrEnum):
    """Migration data-plane executor."""

    GO = "go"
