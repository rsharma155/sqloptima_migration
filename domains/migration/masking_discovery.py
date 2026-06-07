"""Auto-discover column sensitivity from source metadata (§12.2).

Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domains.discovery.pii_classifier import SensitivityClass, sensitive_columns
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


@dataclass
class TableMaskingProfile:
    table_name: str
    column_sensitivity: dict[str, str]
    column_types: dict[str, str]
    sensitive_count: int


async def discover_table_masking(
    source_connector: Any,
    *,
    database: str,
    schema: str,
    table_names: list[str],
) -> dict[str, TableMaskingProfile]:
    """Classify columns for each requested table via discovery + PII heuristics."""
    from infrastructure.sqlserver.sqlserver_discovery import SqlServerMetadataDiscovery

    discovery = SqlServerMetadataDiscovery(source_connector)
    discovered = await discovery.discover_tables(database, schema)
    by_name = {t.object_name.lower(): t for t in discovered}

    profiles: dict[str, TableMaskingProfile] = {}
    for table in table_names:
        meta = by_name.get(table.lower())
        if not meta or not meta.columns:
            profiles[table] = TableMaskingProfile(
                table_name=table,
                column_sensitivity={},
                column_types={},
                sensitive_count=0,
            )
            continue

        col_names = [c.column_name for c in meta.columns]
        sens_map = {
            c.column_name: c.sensitivity.value
            for c in sensitive_columns(col_names)
        }
        type_map = {
            c.column_name: c.data_type.type_name.lower()
            for c in meta.columns
            if c.data_type and c.data_type.type_name
        }
        profiles[table] = TableMaskingProfile(
            table_name=table,
            column_sensitivity=sens_map,
            column_types=type_map,
            sensitive_count=len(sens_map),
        )
        logger.info(
            "masking_discovery",
            table=table,
            sensitive_count=len(sens_map),
            columns=list(sens_map.keys()),
        )
    return profiles


def merge_masking_profile(
    profile: TableMaskingProfile,
    *,
    masking_policy: str,
    column_transforms: dict[str, str] | None,
    column_sensitivity: dict[str, str] | None,
) -> tuple[dict[str, str] | None, dict[str, str] | None]:
    """Merge caller overrides with discovered sensitivity for a single table."""
    if masking_policy == "none":
        return column_transforms, None

    discovered = profile.column_sensitivity
    merged_sensitivity = {**discovered, **(column_sensitivity or {})}

    # Explicit transforms override default mask selection in build_pipeline_for_plan.
    transforms = dict(column_transforms or {})
    if masking_policy == "strict" and profile.sensitive_count > 0:
        for col, sens in merged_sensitivity.items():
            if sens == SensitivityClass.NONE.value:
                continue
            if col in transforms and transforms[col] == "identity":
                raise ValueError(
                    f"Strict masking: column '{col}' is {sens} but transform is identity"
                )

    return transforms or None, merged_sensitivity or None
