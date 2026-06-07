# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""Deep health-check probes for the API (Issue #28).

Each external dependency gets its own small, dependency-injected probe so it can
be unit-tested in isolation and composed by :func:`run_all_checks`. The
aggregator is what the ``/health/deep`` endpoint calls.

Design:
    * Probes never raise — they catch and report ``ProbeResult(healthy=False, ...)``
      so one failing dependency cannot break the whole health report.
    * Dependencies are passed in (session factory, secrets manager, redis client)
      rather than imported, keeping the probes pure and testable.
    * An absent *optional* dependency (e.g. Redis) reports healthy/"skipped", not
      a failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of a single dependency probe."""

    name: str
    healthy: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"healthy": self.healthy, "detail": self.detail}


async def check_metadata_db(session_factory: Any) -> ProbeResult:
    """Verify the metadata DB is reachable by issuing ``SELECT 1``."""
    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
        return ProbeResult("metadata_db", True, "reachable")
    except Exception as exc:  # noqa: BLE001 — health probe must not propagate
        return ProbeResult("metadata_db", False, str(exc))


def check_encryption(secrets_manager: Any) -> ProbeResult:
    """Verify the encryption subsystem can round-trip a value.

    A missing SecretsManager (or one that cannot derive a key) is unhealthy,
    since credential decryption would fail at runtime.
    """
    if secrets_manager is None:
        return ProbeResult("encryption", False, "secrets manager not configured")
    try:
        token = secrets_manager.encrypt("healthcheck")
        if secrets_manager.decrypt(token) != "healthcheck":
            return ProbeResult("encryption", False, "round-trip mismatch")
        return ProbeResult("encryption", True, "round-trip ok")
    except Exception as exc:  # noqa: BLE001
        return ProbeResult("encryption", False, str(exc))


async def check_redis(redis_client: Any | None) -> ProbeResult:
    """Ping Redis if configured; an absent client is a skip, not a failure."""
    if redis_client is None:
        return ProbeResult("redis", True, "skipped — not configured")
    try:
        await redis_client.ping()
        return ProbeResult("redis", True, "reachable")
    except Exception as exc:  # noqa: BLE001
        return ProbeResult("redis", False, str(exc))


async def run_all_checks(
    session_factory: Any,
    secrets_manager: Any,
    redis_client: Any | None = None,
) -> dict[str, Any]:
    """Run every probe and aggregate into a single health report."""
    results = [
        await check_metadata_db(session_factory),
        check_encryption(secrets_manager),
        await check_redis(redis_client),
    ]
    return {
        "healthy": all(r.healthy for r in results),
        "checks": {r.name: r.to_dict() for r in results},
    }
