"""Tests for platform replication settings resolution."""

from __future__ import annotations

import pytest

from application.replication_settings_config import (
    ReplicationCaptureSettings,
    replication_settings_status,
    resolved_replication_capture_settings,
)
from apps.api.replication_settings_store import set_settings


@pytest.fixture(autouse=True)
def _reset_replication_settings():
    set_settings({})
    yield
    set_settings({})


def test_resolved_replication_capture_settings_defaults():
    settings = resolved_replication_capture_settings()
    assert settings == ReplicationCaptureSettings()


def test_resolved_replication_capture_settings_custom_values():
    set_settings({"poll_interval_ms": 2500, "batch_size": 500})
    settings = resolved_replication_capture_settings()
    assert settings.poll_interval_ms == 2500
    assert settings.batch_size == 500


def test_replication_settings_status_shape():
    set_settings({"poll_interval_ms": 2000, "batch_size": 250})
    status = replication_settings_status()
    assert status["poll_interval_ms"] == 2000
    assert status["poll_interval_sec"] == 2.0
    assert status["batch_size"] == 250
