"""Tests for the API container entrypoint wait/exec contract."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "scripts" / "docker_api_entrypoint.py"


def _load():
    spec = importlib.util.spec_from_file_location("docker_api_entrypoint", ENTRY)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_wait_skipped_without_metadata_host(monkeypatch):
    mod = _load()
    called = {"wait": False}

    def _boom(*_a, **_k):
        called["wait"] = True
        raise AssertionError("must not wait")

    monkeypatch.setattr(mod, "_wait_for_tcp", _boom)
    monkeypatch.delenv("METADATA_DB_HOST", raising=False)
    monkeypatch.setattr(mod.sys, "argv", ["docker_api_entrypoint.py"])

    def fake_execvp(file, args):
        raise RuntimeError(f"exec:{file}:{list(args)}")

    monkeypatch.setattr(mod.os, "execvp", fake_execvp)
    with pytest.raises(RuntimeError, match="exec:uvicorn:"):
        mod.main()
    assert called["wait"] is False


def test_extra_args_override_uvicorn(monkeypatch):
    mod = _load()
    monkeypatch.delenv("METADATA_DB_HOST", raising=False)
    monkeypatch.setattr(
        mod.sys,
        "argv",
        ["docker_api_entrypoint.py", "uvicorn", "apps.api.main:app", "--reload"],
    )

    def fake_execvp(file, args):
        raise RuntimeError(f"exec:{file}:{list(args)}")

    monkeypatch.setattr(mod.os, "execvp", fake_execvp)
    with pytest.raises(RuntimeError, match="--reload"):
        mod.main()
