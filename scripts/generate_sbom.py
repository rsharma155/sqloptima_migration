#!/usr/bin/env python3
"""Generate CycloneDX SBOM for Python dependencies (§12.9).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


def main() -> int:
    out = Path("dist/sbom-python.json")
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "cyclonedx-bom", "-q"],
            check=True,
        )
        subprocess.run(
            [
                sys.executable, "-m", "cyclonedx_py",
                "environment",
                "-o", str(out),
                "--output-format", "json",
            ],
            check=True,
        )
        print(f"SBOM written to {out}")
        return 0
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fallback: minimal SBOM from pip freeze
        freeze = subprocess.check_output(
            [sys.executable, "-m", "pip", "freeze"], text=True
        )
        components = []
        for line in freeze.strip().splitlines():
            if "==" in line:
                name, version = line.split("==", 1)
                components.append({"type": "library", "name": name, "version": version})
        payload = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.4",
            "version": 1,
            "metadata": {"timestamp": datetime.now(UTC).isoformat()},
            "components": components,
        }
        out.write_text(json.dumps(payload, indent=2))
        print(f"Fallback SBOM written to {out} ({len(components)} components)")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
