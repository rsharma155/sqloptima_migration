"""
Module: models.py
Purpose: Change data capture replication pipeline
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class ReplicationConfig(BaseModel):
    id: str
    name: str
    source_conn: dict[str, Any]
    target_conn: dict[str, Any]
    tables: list[str]
    mode: str = "incremental"
    schedule_cron: str | None = None
    watermark_column: str | None = None
    batch_size: int = 5000
    poll_interval_ms: int = 1000
    parallel_workers: int = 1
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    enabled: bool = True


class ScheduleJob(BaseModel):
    id: str
    config_id: str
    job_type: str
    cron_expression: str | None = None
    next_run_time: datetime | None = None
    last_run_time: datetime | None = None
    status: str = "idle"
    action: str = "replicate_cdc"


class ReplicationStatus(BaseModel):
    config_id: str
    state: str = "IDLE"
    lag_ms: int = 0
    events_captured: int = 0
    events_applied: int = 0
    errors: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    last_heartbeat: datetime | None = None


class ScheduleConfig(BaseModel):
    id: str
    name: str
    cron_expression: str
    timezone: str = "UTC"
    max_instances: int = 1
    coalesce: bool = True
    misfire_grace_time: int = 30
