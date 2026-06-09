# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""Tests for Windows-safe UTF-8 .env handling in start.py."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


@pytest.fixture()
def start_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.chdir(tmp_path)
    env_file = tmp_path / ".env"
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    import start as mod

    importlib.reload(mod)
    monkeypatch.setattr(mod, "ENV_FILE", env_file)
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    return mod


def test_write_env_file_uses_utf8(start_module):
    start_module._write_env_file("# SQL Optima Migration - test\nKEY=value\n")
    raw = start_module.ENV_FILE.read_bytes()
    assert b"\xe2\x80\x94" not in raw  # no UTF-8 em dash from template
    assert start_module.ENV_FILE.read_text(encoding="utf-8").startswith("# SQL Optima")


def test_repair_env_encoding_from_cp1252(start_module):
    # Em dash as Windows cp1252 byte 0x97 (fails Starlette UTF-8 read).
    start_module.ENV_FILE.write_bytes(
        b"# SQL Optima Migration \x97 Environment\nMIGRATION_MASTER_KEY=abc\n"
    )
    assert start_module._repair_env_encoding() is True
    start_module.ENV_FILE.read_text(encoding="utf-8")
    text = start_module.ENV_FILE.read_text(encoding="utf-8")
    assert "MIGRATION_MASTER_KEY=abc" in text


def test_repair_env_encoding_skips_valid_utf8(start_module):
    start_module._write_env_file("MIGRATION_MASTER_KEY=already-utf8\n")
    assert start_module._repair_env_encoding() is False


def test_load_env_reads_repaired_file(start_module, monkeypatch: pytest.MonkeyPatch):
    start_module.ENV_FILE.write_bytes(
        b"MIGRATION_JWT_SECRET=\x97legacy\nMETADATA_DB_URL=postgresql://x\n"
    )
    monkeypatch.delenv("MIGRATION_JWT_SECRET", raising=False)
    start_module.load_env()
    assert "\x97" not in (start_module.os.environ.get("MIGRATION_JWT_SECRET") or "")
