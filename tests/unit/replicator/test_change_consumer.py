"""Unit tests for ReplicationChangeConsumer target table name mapping."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.replicator.capture.models import ChangeEvent, ChangeOperation
from infrastructure.replication.change_consumer import ReplicationChangeConsumer


@pytest.fixture
def mock_connection():
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.transaction = MagicMock()
    return conn


@pytest.mark.asyncio
async def test_preserves_discovered_target_table_name(mock_connection):
    """Quoted PostgreSQL tables keep mixed-case relnames (e.g. Bookings)."""
    applied: list[ChangeEvent] = []

    async def capture_apply(event, pk_columns=None):
        applied.append(event)
        return True

    consumer = ReplicationChangeConsumer(
        mock_connection,
        target_schema="public",
        table_pk_map={"bookings": ["id"]},
        table_target_names={"bookings": "Bookings"},
    )
    consumer._applier.apply = capture_apply  # type: ignore[method-assign]

    event = ChangeEvent(
        table_schema="dbo",
        table_name="Bookings",
        operation=ChangeOperation.INSERT,
        after_values={"id": 1},
    )
    await consumer.handle(event)

    assert len(applied) == 1
    assert applied[0].table_schema == "public"
    assert applied[0].table_name == "Bookings"
