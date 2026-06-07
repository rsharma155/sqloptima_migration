"""Tests for platform migration settings resolution."""

from __future__ import annotations

import pytest

from application.migration_settings_config import (
    get_max_tables_per_job,
    migration_settings_status,
    resolved_source_throttle,
)
from apps.api.migration_settings_store import set_settings
from domains.migration.source_throttle import SourceThrottleConfig


@pytest.fixture(autouse=True)
def _reset_migration_settings():
    set_settings({})
    yield
    set_settings({})


def test_resolved_source_throttle_uses_store_defaults():
    throttle = resolved_source_throttle()
    assert throttle == SourceThrottleConfig()


def test_resolved_source_throttle_custom_values():
    set_settings(
        {
            "source_throttle_enabled": False,
            "small_table_delay_sec": 2.5,
            "large_table_delay_sec": 8.0,
            "large_table_row_threshold": 50_000,
            "large_table_size_mb_threshold": 100.0,
        }
    )
    throttle = resolved_source_throttle()
    assert throttle.enabled is False
    assert throttle.small_table_delay_sec == 2.5
    assert throttle.large_table_delay_sec == 8.0
    assert throttle.large_table_row_threshold == 50_000
    assert throttle.large_table_size_mb_threshold == 100.0


def test_get_max_tables_per_job():
    set_settings({"max_tables_per_job": 10})
    assert get_max_tables_per_job() == 10


def test_migration_settings_status_shape():
    set_settings({"max_tables_per_job": 30, "small_table_delay_sec": 0.5})
    status = migration_settings_status()
    assert status["max_tables_per_job"] == 30
    assert status["small_table_delay_sec"] == 0.5
    assert "source_throttle_enabled" in status
