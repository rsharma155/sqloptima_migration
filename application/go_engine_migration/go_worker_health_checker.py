"""
Module: go_worker_health_checker.py
Purpose: Verify the Go migration-engine worker is alive via heartbeats.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from infrastructure.metadata_db.repositories.migration_worker_heartbeat_repository import (
    MigrationWorkerHeartbeatRepository,
)
from infrastructure.metadata_db.session import AsyncSessionFactory


class GoWorkerHealthChecker:
    async def is_worker_alive(self, *, within_seconds: int = 60) -> bool:
        async with AsyncSessionFactory() as session:
            repo = MigrationWorkerHeartbeatRepository(session)
            return await repo.has_recent_heartbeat(within_seconds=within_seconds)

    async def worker_status(self, *, within_seconds: int = 60) -> dict:
        """Return heartbeat summary for admin diagnostics."""
        from datetime import UTC, datetime, timedelta

        async with AsyncSessionFactory() as session:
            repo = MigrationWorkerHeartbeatRepository(session)
            rows = await repo.list_all()

        cutoff = datetime.now(UTC) - timedelta(seconds=within_seconds)
        workers = []
        for row in rows:
            workers.append({
                "worker_id": row.worker_id,
                "status": row.status,
                "engine_version": row.engine_version,
                "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
                "alive": bool(row.last_seen_at and row.last_seen_at >= cutoff),
            })
        alive = any(w["alive"] for w in workers)
        return {
            "alive": alive,
            "within_seconds": within_seconds,
            "workers": workers,
        }
