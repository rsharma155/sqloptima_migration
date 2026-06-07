"""
Module: test_sp_test_conversions.py
Purpose: Convert every SQL Server stored-procedure script in SP_test/sqlserver
         through the application's conversion service (the same code path the
         /api/v1/convert endpoint uses) and assert each one produces a
         successful, non-empty PL/pgSQL result.

These are the reference scripts shipped in SP_test/sqlserver (numbered
01..100). The test is data-driven: dropping a new *.sql file into that folder
automatically adds a case — no edits here required.

Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from pathlib import Path

import pytest

from application.conversion_service import ConversionRequest, ConversionService

# Repo root is two levels up from tests/unit/.
SP_DIR = Path(__file__).resolve().parents[2] / "SP_test" / "sqlserver"

SP_FILES = sorted(SP_DIR.glob("*.sql"), key=lambda p: p.name)


@pytest.fixture(scope="module")
def service() -> ConversionService:
    # Mirrors the API default: dbo→public schema mapping + phase enhancements.
    return ConversionService()


def test_sp_test_directory_is_populated():
    """Guard against an empty/missing fixture folder silently passing."""
    assert SP_DIR.is_dir(), f"SP_test/sqlserver not found at {SP_DIR}"
    assert len(SP_FILES) >= 100, (
        f"Expected at least 100 reference scripts, found {len(SP_FILES)}"
    )


@pytest.mark.parametrize("sql_path", SP_FILES, ids=lambda p: p.name)
def test_sp_converts_to_postgres(sql_path: Path, service: ConversionService):
    """Each SQL Server script converts to non-empty PL/pgSQL without errors."""
    sql = sql_path.read_text(encoding="utf-8")

    result = service.convert(ConversionRequest(sql=sql, object_type="auto"))

    assert result.success, (
        f"{sql_path.name}: conversion failed: {'; '.join(result.errors)}"
    )
    assert result.converted_sql.strip(), (
        f"{sql_path.name}: conversion produced empty output"
    )
