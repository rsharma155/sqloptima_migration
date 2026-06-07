"""Shared slowapi limiter instance for route-level rate limiting.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

try:
    from slowapi import Limiter
    from slowapi.util import get_remote_address

    limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
    available = True
except ImportError:  # pragma: no cover
    limiter = None  # type: ignore[assignment]
    available = False
