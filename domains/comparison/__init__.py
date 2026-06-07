"""
Module: __init__.py
Purpose: Schema comparison utilities
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from domains.comparison.comparison_engine import (
    ComparisonEngine,
    ComparisonResult,
    ComparisonTreeNode,
    MatchStatus,
    ObjectMatch,
)
from domains.comparison.object_comparator import DiffEntry, ObjectComparator

__all__ = [
    "ComparisonEngine",
    "ComparisonResult",
    "ComparisonTreeNode",
    "DiffEntry",
    "MatchStatus",
    "ObjectComparator",
    "ObjectMatch",
]
