"""Connection-string switch manifest for post-cutover (§13.2).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass
class ConnectionSwitchManifest:
    job_id: str
    source_dsn: str
    target_dsn: str
    target_schema: str
    tables: list[str]
    committed_at: str
    instructions: list[str]


class ConnectionSwitchService:
    """Produce an operator-facing manifest for switching apps to PostgreSQL."""

    @staticmethod
    def build_manifest(
        job_id: str,
        source_cfg: dict[str, Any],
        target_cfg: dict[str, Any],
        tables: list[str],
        target_schema: str = "public",
    ) -> ConnectionSwitchManifest:
        src_dsn = (
            f"sqlserver://{source_cfg.get('username')}@"
            f"{source_cfg.get('host')}:{source_cfg.get('port')}/"
            f"{source_cfg.get('database')}"
        )
        tgt_dsn = (
            f"postgresql://{target_cfg.get('username')}@"
            f"{target_cfg.get('host')}:{target_cfg.get('port')}/"
            f"{target_cfg.get('database')}?options=-csearch_path%3D{target_schema}"
        )
        return ConnectionSwitchManifest(
            job_id=job_id,
            source_dsn=src_dsn,
            target_dsn=tgt_dsn,
            target_schema=target_schema,
            tables=tables,
            committed_at=datetime.now(UTC).isoformat(),
            instructions=[
                "1. Confirm validation passed and cutover is committed.",
                "2. Update application connection strings to target_dsn.",
                f"3. Set PostgreSQL search_path to '{target_schema}' or schema-qualify queries.",
                "4. Keep source online read-only for rollback window.",
                "5. Monitor /metrics and validation runs for 24h post-cutover.",
            ],
        )
