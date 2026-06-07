"""Ensure the legacy Python data worker was removed."""

from __future__ import annotations

import application.migration_service as svc


def test_python_data_path_removed() -> None:
    assert not hasattr(svc, "run_migration_background")
