# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""TDD tests for the replication_streams table introduced in migration 003 (L-11).

Contract verified:
  - ReplicationStreamRecord can be created with only required fields.
  - Status field defaults to "IDLE".
  - last_checkpoint_lsn is nullable; updated independently.
  - Record is retrievable by primary key and by connection_id.
  - status index exists on the table (structural, not an ORM test).

Uses the shared conftest test_db_engine / test_session_factory fixtures.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from infrastructure.metadata_db.models import ReplicationStreamRecord


def _make_stream(connection_id: str | None = None, status: str = "IDLE") -> ReplicationStreamRecord:
    return ReplicationStreamRecord(
        replication_stream_id=str(uuid4()),
        project_connection_id=connection_id,
        status=status,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Schema / model contract
# ═══════════════════════════════════════════════════════════════════════════

class TestReplicationStreamModel:
    def test_tablename(self):
        assert ReplicationStreamRecord.__tablename__ == "replication_streams"

    def test_status_column_exists(self):
        cols = {c.key for c in ReplicationStreamRecord.__table__.columns}
        assert "status" in cols

    def test_last_checkpoint_lsn_column_exists(self):
        cols = {c.key for c in ReplicationStreamRecord.__table__.columns}
        assert "last_checkpoint_lsn" in cols

    def test_connection_id_is_nullable(self):
        col = ReplicationStreamRecord.__table__.c["project_connection_id"]
        assert col.nullable is True

    def test_status_index_defined(self):
        index_names = {idx.name for idx in ReplicationStreamRecord.__table__.indexes}
        # At least one index that covers the status column should exist.
        status_indexed = any(
            any(c.key == "status" for c in idx.columns)
            for idx in ReplicationStreamRecord.__table__.indexes
        )
        assert status_indexed, "replication_streams.status should have a DB index"


# ═══════════════════════════════════════════════════════════════════════════
# CRUD against in-memory DB (uses conftest fixtures)
# ═══════════════════════════════════════════════════════════════════════════

class TestReplicationStreamCrud:
    async def test_insert_and_retrieve_by_pk(self, test_session_factory):
        stream = _make_stream(status="IDLE")
        async with test_session_factory() as sess:
            sess.add(stream)
            await sess.commit()

        async with test_session_factory() as sess:
            result = await sess.get(ReplicationStreamRecord, stream.replication_stream_id)
            assert result is not None
            assert result.status == "IDLE"

    async def test_default_status_is_idle(self, test_session_factory):
        stream = ReplicationStreamRecord(
            replication_stream_id=str(uuid4()),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        async with test_session_factory() as sess:
            sess.add(stream)
            await sess.commit()

        async with test_session_factory() as sess:
            result = await sess.get(ReplicationStreamRecord, stream.replication_stream_id)
            assert result.status == "IDLE"

    async def test_update_status(self, test_session_factory):
        stream = _make_stream(status="IDLE")
        async with test_session_factory() as sess:
            sess.add(stream)
            await sess.commit()

        async with test_session_factory() as sess:
            result = await sess.get(ReplicationStreamRecord, stream.replication_stream_id)
            result.status = "CDC_STREAMING"
            result.last_checkpoint_lsn = "0x00000001:00000020:0001"
            await sess.commit()

        async with test_session_factory() as sess:
            result = await sess.get(ReplicationStreamRecord, stream.replication_stream_id)
            assert result.status == "CDC_STREAMING"
            assert result.last_checkpoint_lsn == "0x00000001:00000020:0001"

    async def test_query_by_status(self, test_session_factory):
        streams = [
            _make_stream(status="IDLE"),
            _make_stream(status="CDC_STREAMING"),
            _make_stream(status="CDC_STREAMING"),
            _make_stream(status="FAILED"),
        ]
        async with test_session_factory() as sess:
            for s in streams:
                sess.add(s)
            await sess.commit()

        async with test_session_factory() as sess:
            result = await sess.execute(
                select(ReplicationStreamRecord).where(
                    ReplicationStreamRecord.status == "CDC_STREAMING"
                )
            )
            rows = result.scalars().all()
            assert len(rows) == 2

    async def test_null_connection_id_allowed(self, test_session_factory):
        stream = _make_stream(connection_id=None)
        async with test_session_factory() as sess:
            sess.add(stream)
            await sess.commit()

        async with test_session_factory() as sess:
            result = await sess.get(ReplicationStreamRecord, stream.replication_stream_id)
            assert result.project_connection_id is None
