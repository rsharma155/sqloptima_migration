#!/usr/bin/env python3
"""Wait for metadata Postgres (when configured), then start uvicorn."""
from __future__ import annotations

import os
import socket
import sys
import time


def _wait_for_tcp(host: str, port: int, attempts: int = 60) -> None:
    for _ in range(attempts):
        try:
            with socket.create_connection((host, port), timeout=3):
                return
        except OSError:
            time.sleep(1)
    raise SystemExit(f"timed out waiting for {host}:{port}")


def main() -> None:
    host = os.environ.get("METADATA_DB_HOST", "").strip()
    if host:
        port = int(os.environ.get("METADATA_DB_PORT", "5432"))
        _wait_for_tcp(host, port)

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
