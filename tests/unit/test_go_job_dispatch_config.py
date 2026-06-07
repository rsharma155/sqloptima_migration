"""
Module: test_go_job_dispatch_config.py
Purpose: Unit tests for Go engine job dispatch domain contract.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from domains.migration.go_engine.go_connection_dispatch_ref import GoConnectionDispatchRef
from domains.migration.go_engine.go_executor_kind import GoExecutorKind
from domains.migration.go_engine.go_job_dispatch_config import GoJobDispatchConfig
from domains.migration.go_engine.go_migration_status_mapper import (
    go_status_from_python,
    python_status_from_go,
)
from domains.migration.go_engine.go_table_dispatch_payload import GoTableDispatchPayload
from domains.migration.migration_engine import MigrationStatus


def _sample_config() -> GoJobDispatchConfig:
    job_id = uuid4()
    src = uuid4()
    tgt = uuid4()
    return GoJobDispatchConfig(
        job_id=job_id,
        executor=GoExecutorKind.GO,
        source=GoConnectionDispatchRef(connection_id=src, schema="dbo"),
        target=GoConnectionDispatchRef(connection_id=tgt, schema="public"),
        tables=(
            GoTableDispatchPayload(
                table_name="Customers",
                source_schema="dbo",
                target_schema="public",
                columns=["Id", "Name"],
                chunk_size=10_000,
                parallel_workers=4,
                strategy="chunked",
            ),
        ),
        snapshot_ref="snap-1",
    )


class TestGoJobDispatchConfig:
    def test_round_trip_dict(self):
        cfg = _sample_config()
        restored = GoJobDispatchConfig.from_dict(cfg.to_dict())
        assert restored.job_id == cfg.job_id
        assert restored.tables[0].columns == ["Id", "Name"]

    def test_validate_rejects_wildcard_columns(self):
        cfg = _sample_config()
        bad = GoJobDispatchConfig(
            job_id=cfg.job_id,
            executor=GoExecutorKind.GO,
            source=cfg.source,
            target=cfg.target,
            tables=(
                GoTableDispatchPayload(
                    table_name="Customers",
                    source_schema="dbo",
                    target_schema="public",
                    columns=["*"],
                    chunk_size=10_000,
                    parallel_workers=4,
                    strategy="chunked",
                ),
            ),
        )
        with pytest.raises(ValueError, match="wildcard"):
            bad.validate()

    def test_validate_requires_tables(self):
        cfg = GoJobDispatchConfig(
            job_id=uuid4(),
            executor=GoExecutorKind.GO,
            source=GoConnectionDispatchRef(uuid4(), "dbo"),
            target=GoConnectionDispatchRef(uuid4(), "public"),
            tables=(),
        )
        with pytest.raises(ValueError, match="at least one table"):
            cfg.validate()


class TestGoMigrationStatusMapper:
    def test_python_to_go_and_back(self):
        assert go_status_from_python(MigrationStatus.QUEUED) == "QUEUED"
        assert python_status_from_go("RUNNING") == MigrationStatus.RUNNING

    def test_unknown_go_status_raises(self):
        with pytest.raises(ValueError):
            python_status_from_go("BOGUS")
