"""Pre-migration target snapshot safety gate (§13.3).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


@dataclass
class SnapshotResult:
    verified: bool
    snapshot_ref: str | None = None
    message: str = ""
    created: bool = False


class SnapshotGate:
    """Verify or create a target snapshot before destructive migration."""

    def __init__(self, snapshot_dir: str | None = None) -> None:
        self._dir = Path(snapshot_dir or os.environ.get("MIGRATION_SNAPSHOT_DIR", "./snapshots"))

    async def verify_or_create(
        self,
        target_connector: Any,
        *,
        database: str,
        tables: list[str],
        schema: str = "public",
        require_snapshot: bool = True,
        existing_ref: str | None = None,
    ) -> SnapshotResult:
        if existing_ref:
            return await self._verify_ref(existing_ref)

        if not require_snapshot:
            return SnapshotResult(verified=True, message="Snapshot gate disabled")

        if not shutil.which("pg_dump"):
            if os.environ.get("MIGRATION_ALLOW_NO_SNAPSHOT") == "1":
                return SnapshotResult(
                    verified=True,
                    message="pg_dump unavailable; MIGRATION_ALLOW_NO_SNAPSHOT=1 override",
                )
            return SnapshotResult(
                verified=False,
                message="pg_dump not found — install PostgreSQL client tools or set snapshot_ref",
            )

        return await self._create_snapshot(target_connector, database, tables, schema)

    async def _verify_ref(self, ref: str) -> SnapshotResult:
        path = Path(ref)
        if path.exists() and path.stat().st_size > 0:
            return SnapshotResult(verified=True, snapshot_ref=ref, message="Snapshot file verified")
        if ref.startswith("s3://") or ref.startswith("gs://"):
            return SnapshotResult(
                verified=True,
                snapshot_ref=ref,
                message="External snapshot ref accepted (operator-verified)",
            )
        return SnapshotResult(verified=False, snapshot_ref=ref, message=f"Snapshot not found: {ref}")

    async def _create_snapshot(
        self,
        connector: Any,
        database: str,
        tables: list[str],
        schema: str,
    ) -> SnapshotResult:
        self._dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        ref = str(self._dir / f"{database}_{ts}_{uuid4().hex[:8]}.sql")

        host = getattr(getattr(connector, "_config", None), "host", "localhost")
        port = getattr(getattr(connector, "_config", None), "port", 5432)
        user = getattr(getattr(connector, "_config", None), "username", "postgres")
        password = getattr(getattr(connector, "_config", None), "password", "")

        table_args: list[str] = []
        for t in tables:
            table_args.extend(["-t", f"{schema}.{t}"])

        env = {**os.environ, "PGPASSWORD": password}
        cmd = [
            "pg_dump",
            "-h", str(host),
            "-p", str(port),
            "-U", user,
            "-d", database,
            "-Fc",
            "-f", ref,
            *table_args,
        ]

        loop = asyncio.get_running_loop()

        def _run() -> int:
            import subprocess
            proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr or proc.stdout or "pg_dump failed")
            return proc.returncode

        try:
            await loop.run_in_executor(None, _run)
            logger.info("snapshot_created", ref=ref, tables=tables)
            return SnapshotResult(
                verified=True,
                snapshot_ref=ref,
                created=True,
                message=f"pg_dump snapshot created: {ref}",
            )
        except Exception as exc:
            return SnapshotResult(verified=False, message=str(exc))
