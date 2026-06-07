"""
Module: cdc_requirements.py
Purpose: Validate SQL Server CDC prerequisites for replication streams
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CdcStatus:
    db_enabled: bool
    tables: dict[str, bool]


def _table_tracked(tables_map: dict[str, bool], name: str) -> bool:
    for key, tracked in tables_map.items():
        if key.lower() == name.lower():
            return tracked
    return False


def validate_cdc_for_tables(status: CdcStatus, table_names: list[str]) -> str | None:
    """Return an error message if CDC prerequisites are not met, else None."""
    if not status.db_enabled:
        return (
            "SQL Server CDC is not enabled on the source database. "
            "Enable it first, then enable CDC on each table you want to replicate:\n"
            "  EXEC sys.sp_cdc_enable_db;\n"
            "  EXEC sys.sp_cdc_enable_table "
            "@source_schema = N'dbo', @source_name = N'YourTable', @role_name = NULL;"
        )

    untracked = [t for t in table_names if not _table_tracked(status.tables, t)]
    if untracked:
        joined = ", ".join(untracked)
        return (
            f"CDC is not enabled for table(s): {joined}. "
            "Enable CDC on each table before creating a replication stream:\n"
            "  EXEC sys.sp_cdc_enable_table "
            "@source_schema = N'<schema>', @source_name = N'<table>', @role_name = NULL;"
        )
    return None
