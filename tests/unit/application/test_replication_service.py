"""
Module: test_replication_service.py
Purpose: TDD tests for replication application service
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from application.replication_runtime import get_runtime_manager
from application.replication_service import (
    create_stream,
    pause_stream,
    resume_stream,
    start_stream,
    stop_stream,
)
from domains.replication.cdc_requirements import CdcStatus
from domains.replication.schema_drift_detector import TableSchemaSnapshot


@pytest.fixture(autouse=True)
async def _clean_runtime():
    yield
    await get_runtime_manager().stop_all()


_CDC_OK = CdcStatus(db_enabled=True, tables={"Orders": True, "T1": True})


def _mock_cdc_provider() -> MagicMock:
    from apps.replicator.capture.models import TableInfo

    provider = MagicMock()
    provider.connect = AsyncMock()
    provider.discover_tables = AsyncMock(
        return_value=[
            TableInfo(
                schema_name="dbo",
                table_name="T1",
                columns=["id"],
                pk_columns=["id"],
            ),
        ],
    )
    provider.capture_changes = AsyncMock()
    provider.take_snapshot = AsyncMock()
    return provider


class TestReplicationServiceCreate:
    async def test_create_rejects_when_cdc_disabled(self, patch_db_session):
        with patch(
            "application.replication_service.fetch_cdc_status",
            AsyncMock(return_value=CdcStatus(db_enabled=False, tables={})),
        ):
            with pytest.raises(ValueError, match="sp_cdc_enable_db"):
                await create_stream(
                    name="blocked",
                    source_connection_id=str(uuid4()),
                    target_connection_id=str(uuid4()),
                    tables=["Orders"],
                )

    async def test_create_stream_persists_concerns(self, patch_db_session):
        with patch(
            "application.replication_service.fetch_cdc_status",
            AsyncMock(return_value=_CDC_OK),
        ):
            result = await create_stream(
                name="orders-stream",
                source_connection_id=str(uuid4()),
                target_connection_id=str(uuid4()),
                tables=["Orders"],
                source_snapshots=[
                    TableSchemaSnapshot("dbo", "Orders", ["id", "status"], ["id"]),
                ],
                target_snapshots={},
            )
        assert result["name"] == "orders-stream"
        assert result["status"] == "IDLE"
        assert any(c["level"] == "blocker" for c in result["concerns"])

    async def test_create_rejects_invalid_table_name(self, patch_db_session):
        with pytest.raises(ValueError):
            await create_stream(
                name="bad",
                source_connection_id=str(uuid4()),
                target_connection_id=str(uuid4()),
                tables=["bad-name"],
            )


class TestReplicationServiceLifecycle:
    async def test_start_blocked_when_blockers_present(self, patch_db_session):
        with (
            patch(
                "application.replication_service.fetch_cdc_status",
                AsyncMock(return_value=_CDC_OK),
            ),
            patch(
                "application.replication_service._fetch_target_only_snapshots",
                AsyncMock(return_value=({}, "public")),
            ),
            patch(
                "application.replication_service._fetch_schema_snapshots",
                AsyncMock(return_value=([], {})),
            ),
        ):
            created = await create_stream(
                name="blocked",
                source_connection_id=str(uuid4()),
                target_connection_id=str(uuid4()),
                tables=["T1"],
            )
            with pytest.raises(ValueError, match="blocker"):
                await start_stream(created["stream_id"])

    async def test_pause_resume_active_stream(self, patch_db_session):
        with patch(
            "application.replication_service.fetch_cdc_status",
            AsyncMock(return_value=_CDC_OK),
        ):
            created = await create_stream(
                name="active",
                source_connection_id=str(uuid4()),
                target_connection_id=str(uuid4()),
                tables=["T1"],
                source_snapshots=[TableSchemaSnapshot("dbo", "T1", ["id"], ["id"])],
                target_snapshots={"t1": TableSchemaSnapshot("public", "T1", ["id"], ["id"])},
            )
            stream_id = created["stream_id"]

            mock_conn = MagicMock()
            with (
                patch(
                    "application.replication_service._open_target_connection",
                    AsyncMock(return_value=mock_conn),
                ),
                patch(
                    "application.replication_service.fetch_cdc_status",
                    AsyncMock(return_value=_CDC_OK),
                ),
                patch(
                    "application.replication_service.refresh_stream_concerns",
                    AsyncMock(return_value=[]),
                ),
                patch(
                    "application.replication_service.reconcile_stream_runtime",
                    AsyncMock(return_value=None),
                ),
                patch(
                    "application.replication_service._build_source_provider",
                    AsyncMock(return_value=_mock_cdc_provider()),
                ),
                patch(
                    "apps.replicator.apply.checkpoint.CheckpointStore",
                ) as mock_checkpoint_cls,
            ):
                mock_checkpoint_cls.return_value.ensure_table = AsyncMock()
                started = await start_stream(stream_id)
                assert started["status"] == "CDC_STREAMING"

                paused = await pause_stream(stream_id)
                assert paused["status"] == "PAUSED"

                resumed = await resume_stream(stream_id)
                assert resumed["status"] == "CDC_STREAMING"

                stopped = await stop_stream(stream_id)
                assert stopped["status"] == "COMPLETED"
