"""
Module: shared/contracts/config_validation.py
Purpose: Pure validators for connection configuration (port range, pool bounds).
         Kept as small standalone functions so every connector validates the
         same way and the rules are independently unit-testable (Issue #27).
Domain: Contracts
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

MIN_PORT = 1
MAX_PORT = 65535


def validate_port(port: int) -> None:
    """Raise ValueError if *port* is outside the valid TCP range (1..65535)."""
    if not isinstance(port, int) or not (MIN_PORT <= port <= MAX_PORT):
        raise ValueError(
            f"Invalid port {port!r}: must be an integer in [{MIN_PORT}, {MAX_PORT}]."
        )


def validate_pool_bounds(min_size: int, max_size: int) -> None:
    """Raise ValueError if connection-pool bounds are nonsensical.

    Requires ``min_size >= 1`` and ``max_size >= min_size``.
    """
    if min_size < 1:
        raise ValueError(f"min_pool_size must be >= 1 (got {min_size}).")
    if max_size < min_size:
        raise ValueError(
            f"max_pool_size ({max_size}) must be >= min_pool_size ({min_size})."
        )
