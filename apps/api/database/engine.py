"""Backward-compat shim — delegates to infrastructure/metadata_db/session.py.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from infrastructure.metadata_db.session import AsyncSessionFactory, init_db

__all__ = ["AsyncSessionFactory", "init_db"]
