# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""TDD tests for apps/api/startup_checks.py (L-15).

Contract:
  - check_metadata_db() raises RuntimeError when the DB is unreachable.
  - check_metadata_db() returns None (success) when SELECT 1 succeeds.
  - check_odbc_driver() returns a list of installed driver names (possibly empty).
  - check_odbc_driver() returns [] when pyodbc is not installed (no exception).
  - run_startup_checks() calls both checks and logs a summary.
  - run_startup_checks() propagates the RuntimeError from check_metadata_db().
  - run_startup_checks() does NOT raise if ODBC check finds no SQL Server driver.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.startup_checks import (
    StartupCheckResult,
    check_metadata_db,
    check_odbc_driver,
    run_startup_checks,
)


# ═══════════════════════════════════════════════════════════════════════════
# check_metadata_db
# ═══════════════════════════════════════════════════════════════════════════

class TestCheckMetadataDb:
    async def test_returns_result_with_ok_true_when_db_reachable(self):
        mock_sess = AsyncMock()
        mock_sess.execute = AsyncMock()

        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_sess)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await check_metadata_db(session_factory=mock_factory)

        assert result.ok is True
        assert result.error is None
        mock_sess.execute.assert_called_once()

    async def test_returns_result_with_ok_false_when_db_unreachable(self):
        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(
            side_effect=ConnectionRefusedError("DB refused")
        )
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await check_metadata_db(session_factory=mock_factory)

        assert result.ok is False
        assert "DB refused" in (result.error or "")

    async def test_returns_result_with_ok_false_on_generic_exception(self):
        mock_sess = AsyncMock()
        mock_sess.execute = AsyncMock(side_effect=OSError("socket error"))

        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_sess)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await check_metadata_db(session_factory=mock_factory)

        assert result.ok is False
        assert "socket error" in (result.error or "")


# ═══════════════════════════════════════════════════════════════════════════
# check_odbc_driver
# ═══════════════════════════════════════════════════════════════════════════

class TestCheckOdbcDriver:
    def test_returns_drivers_when_pyodbc_available(self):
        fake_drivers = [
            "ODBC Driver 18 for SQL Server",
            "PostgreSQL Unicode",
        ]
        with patch("apps.api.startup_checks.pyodbc", create=True) as mock_pyodbc:
            mock_pyodbc.drivers.return_value = fake_drivers
            result = check_odbc_driver()

        assert result.ok is True
        assert "ODBC Driver 18 for SQL Server" in result.drivers

    def test_returns_ok_false_when_no_sqlserver_driver(self):
        with patch("apps.api.startup_checks.pyodbc", create=True) as mock_pyodbc:
            mock_pyodbc.drivers.return_value = ["PostgreSQL Unicode"]
            result = check_odbc_driver()

        assert result.ok is False
        assert result.drivers == ["PostgreSQL Unicode"]

    def test_returns_empty_list_when_pyodbc_not_installed(self):
        # Patch the already-bound module-level name in startup_checks
        with patch("apps.api.startup_checks.pyodbc", None):
            result = check_odbc_driver()

        assert result.drivers == []
        assert result.ok is False

    def test_returns_empty_when_pyodbc_drivers_raises(self):
        # Simulate pyodbc present but pyodbc.drivers() fails (e.g. shared-library missing)
        mock_pyodbc = MagicMock()
        mock_pyodbc.drivers.side_effect = OSError("libodbc.so not found")
        with patch("apps.api.startup_checks.pyodbc", mock_pyodbc):
            result = check_odbc_driver()

        assert result.drivers == []
        assert result.ok is False


# ═══════════════════════════════════════════════════════════════════════════
# run_startup_checks (orchestration)
# ═══════════════════════════════════════════════════════════════════════════

class TestRunStartupChecks:
    async def test_succeeds_when_db_ok_and_odbc_present(self):
        ok_db = StartupCheckResult(ok=True)
        ok_odbc = StartupCheckResult(ok=True, drivers=["ODBC Driver 18 for SQL Server"])

        with (
            patch("apps.api.startup_checks.check_metadata_db", AsyncMock(return_value=ok_db)),
            patch("apps.api.startup_checks.check_odbc_driver", MagicMock(return_value=ok_odbc)),
        ):
            await run_startup_checks()  # must not raise

    async def test_raises_runtime_error_when_db_unreachable(self):
        fail_db = StartupCheckResult(ok=False, error="connection refused")
        ok_odbc = StartupCheckResult(ok=True, drivers=["ODBC Driver 18 for SQL Server"])

        with (
            patch("apps.api.startup_checks.check_metadata_db", AsyncMock(return_value=fail_db)),
            patch("apps.api.startup_checks.check_odbc_driver", MagicMock(return_value=ok_odbc)),
        ):
            with pytest.raises(RuntimeError, match="metadata database"):
                await run_startup_checks()

    async def test_does_not_raise_when_odbc_missing_but_db_ok(self):
        ok_db = StartupCheckResult(ok=True)
        no_odbc = StartupCheckResult(ok=False, drivers=[])

        with (
            patch("apps.api.startup_checks.check_metadata_db", AsyncMock(return_value=ok_db)),
            patch("apps.api.startup_checks.check_odbc_driver", MagicMock(return_value=no_odbc)),
        ):
            await run_startup_checks()  # ODBC absence is a warning, NOT a hard failure

    async def test_db_failure_takes_priority_over_odbc_failure(self):
        fail_db = StartupCheckResult(ok=False, error="timeout")
        no_odbc = StartupCheckResult(ok=False, drivers=[])

        with (
            patch("apps.api.startup_checks.check_metadata_db", AsyncMock(return_value=fail_db)),
            patch("apps.api.startup_checks.check_odbc_driver", MagicMock(return_value=no_odbc)),
        ):
            with pytest.raises(RuntimeError):
                await run_startup_checks()


# ═══════════════════════════════════════════════════════════════════════════
# StartupCheckResult value object
# ═══════════════════════════════════════════════════════════════════════════

class TestStartupCheckResult:
    def test_default_ok_false(self):
        r = StartupCheckResult()
        assert r.ok is False

    def test_ok_result(self):
        r = StartupCheckResult(ok=True)
        assert r.ok is True
        assert r.error is None

    def test_failure_with_message(self):
        r = StartupCheckResult(ok=False, error="timeout")
        assert r.ok is False
        assert r.error == "timeout"

    def test_drivers_defaults_empty(self):
        r = StartupCheckResult(ok=True)
        assert r.drivers == []
