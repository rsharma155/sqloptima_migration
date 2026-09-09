#!/usr/bin/env python3
"""Wait for metadata Postgres (when configured), then start uvicorn."""
from __future__ import annotations

import os
import socket
import sys
import time
from urllib.parse import quote


def _wait_for_tcp(host: str, port: int, attempts: int = 60) -> None:
    for _ in range(attempts):
        try:
            with socket.create_connection((host, port), timeout=3):
                return
        except OSError:
            time.sleep(1)
    raise SystemExit(f"timed out waiting for {host}:{port}")


def ensure_metadata_urls() -> None:
    """Build DB URLs from discrete env vars so Compose does not interpolate passwords into YAML URLs."""
    host = os.environ.get("METADATA_DB_HOST", "").strip()
    password = os.environ.get("METADATA_DB_PASSWORD", "")
    if not host or not password:
        return
    user = os.environ.get("METADATA_DB_USER", "postgres")
    port = os.environ.get("METADATA_DB_PORT", "5432")
    name = os.environ.get("METADATA_DB_NAME", "migration_checklist")
    auth = f"{quote(user, safe='')}:{quote(password, safe='')}"
    os.environ["METADATA_DB_URL"] = f"postgresql+asyncpg://{auth}@{host}:{port}/{name}"
    os.environ["MIGRATION_DATABASE_METADATA_URL"] = f"postgresql://{auth}@{host}:{port}/{name}"


def main() -> None:
    ensure_metadata_urls()
    host = os.environ.get("METADATA_DB_HOST", "").strip()
    if host:
        port = int(os.environ.get("METADATA_DB_PORT", "5432"))
        _wait_for_tcp(host, port)
        time.sleep(1)

    extra = sys.argv[1:]
    if extra:
        os.execvp(extra[0], extra)

    os.execvp(
        "uvicorn",
        [
            "uvicorn",
            "apps.api.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8508",
            "--proxy-headers",
        ],
    )


if __name__ == "__main__":
    main()
