# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""Startup readiness checks for the Migration Platform API (L-15).

Domain: Interface / Application bootstrap
Module: apps.api.startup_checks

Checks performed at startup:
  1. Metadata DB connectivity — hard failure if unreachable.
  2. ODBC driver availability  — soft warning; SQL Server migrations
     will fail later, but the API can still serve non-SQL-Server paths.

Usage (from main.py startup event)::

    from apps.api.startup_checks import run_startup_checks
    await run_startup_checks()
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


# ── Try to import pyodbc at module level so tests can patch it cleanly ───────
try:
    import pyodbc  # type: ignore[import]
except (ImportError, ModuleNotFoundError):
    pyodbc = None  # type: ignore[assignment]


# ═══════════════════════════════════════════════════════════════════════════
# Value object
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class StartupCheckResult:
    """Immutable result from a single readiness check."""

    ok: bool = False
    error: str | None = None
    drivers: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# Individual checks
# ═══════════════════════════════════════════════════════════════════════════

async def check_metadata_db(
    session_factory: Any = None,
) -> StartupCheckResult:
    """Verify the metadata database is reachable by running SELECT 1.

    Args:
        session_factory: Async session factory to use.  Defaults to the
            module-level singleton from ``infrastructure.metadata_db.session``.

    Returns:
        StartupCheckResult with ok=True on success, ok=False + error on failure.
    """
    if session_factory is None:
        from infrastructure.metadata_db.session import AsyncSessionFactory
        session_factory = AsyncSessionFactory

    try:
        from sqlalchemy import text
        async with session_factory() as sess:
            await sess.execute(text("SELECT 1"))
        logger.info("startup_check_db_ok")
        return StartupCheckResult(ok=True)
    except Exception as exc:
        logger.error("startup_check_db_failed", error=str(exc))
        return StartupCheckResult(ok=False, error=str(exc))


def check_odbc_driver() -> StartupCheckResult:
    """Return available ODBC driver names.

    Returns:
        StartupCheckResult where ``ok`` is True iff at least one SQL Server
        ODBC driver is installed, and ``drivers`` contains every driver found.
        Returns ok=False with an empty ``drivers`` list when pyodbc is absent.
    """
    if pyodbc is None:
        logger.warning("startup_check_odbc_pyodbc_missing")
        return StartupCheckResult(ok=False, drivers=[])

    try:
        all_drivers: list[str] = list(pyodbc.drivers())
        has_sqlserver = any(
            "SQL Server" in d or "ODBC Driver" in d for d in all_drivers
        )
        if has_sqlserver:
            logger.info("startup_check_odbc_ok", drivers=all_drivers)
        else:
            logger.warning(
                "startup_check_odbc_no_sqlserver_driver",
                installed=all_drivers,
                hint="Install 'ODBC Driver 18 for SQL Server' to use SQL Server sources",
            )
        return StartupCheckResult(ok=has_sqlserver, drivers=all_drivers)
    except Exception as exc:
        logger.warning("startup_check_odbc_error", error=str(exc))
        return StartupCheckResult(ok=False, drivers=[])


# ═══════════════════════════════════════════════════════════════════════════
# Orchestrator
# ═══════════════════════════════════════════════════════════════════════════

async def run_startup_checks(session_factory: Any = None) -> None:
    """Run all readiness checks and raise RuntimeError on hard failures.

    Hard failures (raise RuntimeError):
      - Metadata DB unreachable.

    Soft failures (log warning, continue):
      - No SQL Server ODBC driver installed.

    Args:
        session_factory: Injected for testing; defaults to the module singleton.

    Raises:
        RuntimeError: If the metadata database is unreachable.
    """
    db_result = await check_metadata_db(session_factory=session_factory)
    odbc_result = check_odbc_driver()

    if not db_result.ok:
        raise RuntimeError(
            f"Startup readiness check FAILED — cannot reach the metadata database: "
            f"{db_result.error}. "
            f"Ensure METADATA_DB_URL is correct and the database is running."
        )

    if not odbc_result.ok:
        logger.warning(
            "startup_check_odbc_soft_failure",
            message="SQL Server ODBC driver not found — SQL Server source connections will fail at runtime.",
            installed_drivers=odbc_result.drivers,
        )

    logger.info(
        "startup_checks_passed",
        db_ok=db_result.ok,
        odbc_ok=odbc_result.ok,
        odbc_drivers=len(odbc_result.drivers),
    )
