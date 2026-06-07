"""Unit tests for write-freeze coordinator."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from domains.orchestration.write_freeze import WriteFreezeCoordinator


@pytest.mark.asyncio
async def test_freeze_captures_row_counts():
    source = AsyncMock()
    source.execute = AsyncMock(side_effect=[
        [{"cnt": 100}],
        [{"cnt": 250}],
    ])
    coord = WriteFreezeCoordinator(source)
    state = await coord.freeze("dbo", ["users", "orders"])
    assert state.frozen is True
    assert state.source_row_counts == {"users": 100, "orders": 250}


@pytest.mark.asyncio
async def test_verify_no_new_writes_passes():
    source = AsyncMock()
    source.execute = AsyncMock(side_effect=[
        [{"cnt": 100}],
        [{"cnt": 250}],
    ])
    coord = WriteFreezeCoordinator(source)
    ok, counts = await coord.verify_no_new_writes("dbo", {"users": 100, "orders": 250})
    assert ok is True
    assert counts == {"users": 100, "orders": 250}


@pytest.mark.asyncio
async def test_verify_detects_new_writes():
    source = AsyncMock()
    source.execute = AsyncMock(return_value=[{"cnt": 105}])
    coord = WriteFreezeCoordinator(source)
    ok, _ = await coord.verify_no_new_writes("dbo", {"users": 100})
    assert ok is False
