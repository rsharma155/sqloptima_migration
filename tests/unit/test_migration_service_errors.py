"""
Module: tests/unit/test_migration_service_errors.py
Purpose: Tests for migration failure-reason capture (Issue #2) — dispatch must
         record WHY a job failed, not just flip it to FAILED.
Domain: Application
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import pytest

import application.migration_service as svc
from application.go_engine_migration.go_migration_job_dispatcher import (
    dispatch_migration_job_to_go_engine,
)
from domains.migration.migration_engine import MigrationJob, MigrationStatus


class TestMigrationJobErrorField:
    def test_job_has_error_message_default_none(self):
        job = MigrationJob()
        assert job.error_message is None


class TestDispatchErrorCapture:
    @pytest.mark.asyncio
    async def test_records_error_on_missing_connections(self, monkeypatch):
        """When the source connection entry is missing, dispatch must mark the
        job FAILED and record an explanatory error_message."""
        monkeypatch.setattr(
            "apps.api.connection_store.get_entry", lambda _id: None, raising=True
        )
        job = MigrationJob()
        svc._registry.put(job)
        try:
            await dispatch_migration_job_to_go_engine(job.job_id)
            assert job.status == MigrationStatus.FAILED
            assert job.error_message
            assert "connection" in job.error_message.lower()
        finally:
            svc._registry.discard(job.job_id)
