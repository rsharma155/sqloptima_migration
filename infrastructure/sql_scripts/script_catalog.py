# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""Load least-privilege bootstrap scripts from infrastructure/sql_scripts/."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_SCRIPTS_ROOT = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def _load_manifest() -> dict[str, Any]:
    with (_SCRIPTS_ROOT / "manifest.json").open(encoding="utf-8") as fh:
        return json.load(fh)


def _script_entry(target: str) -> dict[str, Any]:
    manifest = _load_manifest()
    for script in manifest.get("scripts", []):
        if script.get("target") == target:
            return script
    raise KeyError(f"No script registered for target={target!r}")


def _read_script(relative_path: str) -> str:
    path = _SCRIPTS_ROOT / relative_path
    return path.read_text(encoding="utf-8")


def get_privilege_script_bundle() -> dict[str, Any]:
    """Return source/target least-privilege scripts with metadata for the UI."""
    manifest = _load_manifest()
    source_meta = manifest.get("migration_source", {})
    target_meta = manifest.get("migration_target", {})

    source_script = _script_entry("migration_source")
    target_script = _script_entry("migration_target")

    return {
        "source": {
            "engine": source_meta.get("engine", "sqlserver"),
            "title": "SQL Server source (read-only)",
            "recommended_login": source_meta.get("recommended_login", "migration_reader"),
            "privileges": source_meta.get("privileges", []),
            "capabilities": source_meta.get("capabilities", []),
            "not_granted": source_meta.get("not_granted", []),
            "file": source_script["file"],
            "purpose": source_script.get("purpose", ""),
            "variables": source_script.get("variables", {}),
            "run_example": source_script.get("run_example", ""),
            "content": _read_script(source_script["file"]),
        },
        "target": {
            "engine": target_meta.get("engine", "postgresql"),
            "title": "PostgreSQL target (DDL + DML)",
            "recommended_role": target_meta.get("recommended_role", "migration_writer"),
            "default_schema": target_meta.get("default_schema", "public"),
            "privileges": target_meta.get("privileges", []),
            "capabilities": target_meta.get("capabilities", []),
            "not_granted": target_meta.get("not_granted", []),
            "file": target_script["file"],
            "purpose": target_script.get("purpose", ""),
            "variables": target_script.get("variables", {}),
            "run_example": target_script.get("run_example", ""),
            "content": _read_script(target_script["file"]),
        },
    }
