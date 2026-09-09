"""Unit tests for platform Transfer settings (file offload) and live metrics."""

from __future__ import annotations

import pytest

from domains.transfer.transfer_settings import (
    DEFAULT_FILE_OFFLOAD_MIN_MB,
    DEFAULT_FILE_OFFLOAD_MIN_ROWS,
    TransferSettingsError,
    default_transfer_settings,
    should_file_offload,
    validate_transfer_settings,
)
from application.transfer_service import build_live_metrics


def test_default_file_offload_threshold_is_two_million_rows():
    settings = default_transfer_settings()
    assert settings["file_offload_enabled"] is True
    assert settings["file_offload_min_rows"] == 2_000_000
    assert settings["file_offload_min_mb"] == DEFAULT_FILE_OFFLOAD_MIN_MB
    assert settings["staging_path"] == ""


def test_should_file_offload_never_on_same_server():
    assert (
        should_file_offload(
            enabled=True,
            min_rows=DEFAULT_FILE_OFFLOAD_MIN_ROWS,
            min_mb=256.0,
            row_estimate=10_000_000,
            size_mb=4_000.0,
            same_server=True,
        )
        is False
    )


def test_should_file_offload_when_rows_meet_threshold_cross_server():
    assert (
        should_file_offload(
            enabled=True,
            min_rows=2_000_000,
            min_mb=256.0,
            row_estimate=2_000_000,
            size_mb=10.0,
            same_server=False,
        )
        is True
    )


def test_should_file_offload_when_size_meets_threshold():
    assert (
        should_file_offload(
            enabled=True,
            min_rows=2_000_000,
            min_mb=256.0,
            row_estimate=50_000,
            size_mb=256.0,
            same_server=False,
        )
        is True
    )


def test_should_file_offload_disabled_at_app_level():
    assert (
        should_file_offload(
            enabled=False,
            min_rows=1,
            min_mb=1.0,
            row_estimate=10_000_000,
            size_mb=4_000.0,
            same_server=False,
        )
        is False
    )


def test_validate_transfer_settings_rejects_non_positive_rows():
    with pytest.raises(TransferSettingsError, match="min_rows"):
        validate_transfer_settings({"file_offload_min_rows": 0})


def test_validate_transfer_settings_rejects_oversized_staging_path():
    with pytest.raises(TransferSettingsError, match="staging_path"):
        validate_transfer_settings({"staging_path": "x" * 2000})


def test_build_live_metrics_exposes_every_configured_table_and_errors():
    job = {
        "job_id": "job-1",
        "status": "running",
        "phase": "loading",
        "overall_percentage": 40.0,
        "rows_copied": 400,
        "rows_total": 1000,
        "tables_total": 2,
        "tables_done": 1,
        "threshold": {"chunk_size": 10_000},
        "tables": [
            {
                "source_schema": "dbo",
                "source_table": "orders",
                "target_schema": "dbo",
                "target_table": "orders",
                "status": "completed",
                "rows_copied": 400,
                "row_count_estimate": 400,
                "error": None,
                "error_count": 0,
            },
            {
                "source_schema": "dbo",
                "source_table": "payments",
                "target_schema": "dbo",
                "target_table": "payments",
                "status": "failed",
                "rows_copied": 0,
                "row_count_estimate": 600,
                "error": "BULK INSERT failed: timeout",
                "error_count": 1,
            },
        ],
    }
    metrics = build_live_metrics(job)
    assert metrics["tables_failed"] == 1
    assert metrics["tables_running"] == 0
    assert len(metrics["tables"]) == 2
    payments = next(t for t in metrics["tables"] if t["source_table"] == "payments")
    assert payments["error"] == "BULK INSERT failed: timeout"
    assert payments["table_key"] == "dbo.payments"
    assert payments["percent"] == 0.0
    orders = next(t for t in metrics["tables"] if t["source_table"] == "orders")
    assert orders["percent"] == 100.0
