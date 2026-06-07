"""
Module: tests/unit/replicator/test_deduplicator.py
Purpose: Unit tests for Deduplicator (LSN-based dedup cache)
Author: Migration Platform Team
Created: 2026-05-22
Domain: Replication / Apply
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from unittest.mock import AsyncMock

import pytest

from apps.replicator.apply.deduplicator import Deduplicator
from apps.replicator.capture.models import LsnPosition


class TestDeduplicator:
    @pytest.mark.asyncio
    async def test_already_applied_returns_false_for_new(self):
        dedup = Deduplicator()
        lsn = LsnPosition.from_string("0x00001234:0000ABCD:0001")
        result = await dedup.already_applied(lsn, "dbo.users")
        assert result is False

    @pytest.mark.asyncio
    async def test_record_then_already_applied(self):
        dedup = Deduplicator()
        lsn = LsnPosition.from_string("0x00001234:0000ABCD:0001")
        await dedup.record(lsn, "dbo.users")
        result = await dedup.already_applied(lsn, "dbo.users")
        assert result is True

    @pytest.mark.asyncio
    async def test_same_lsn_different_table(self):
        dedup = Deduplicator()
        lsn = LsnPosition.from_string("0x00001234:0000ABCD:0001")
        await dedup.record(lsn, "dbo.users")
        result = await dedup.already_applied(lsn, "dbo.orders")
        assert result is False

    @pytest.mark.asyncio
    async def test_eviction_under_max_size(self):
        dedup = Deduplicator(max_size=5)
        for i in range(5):
            lsn = LsnPosition.from_string(f"0x00000000:00000000:{i:04X}")
            await dedup.record(lsn, f"dbo.table{i}")
        assert len(dedup._cache) == 5

    @pytest.mark.asyncio
    async def test_eviction_over_max_size(self):
        dedup = Deduplicator(max_size=3)
        for i in range(5):
            lsn = LsnPosition.from_string(f"0x00000000:00000000:{i:04X}")
            await dedup.record(lsn, f"dbo.table{i}")
        assert len(dedup._cache) <= 3

    @pytest.mark.asyncio
    async def test_clear(self):
        dedup = Deduplicator()
        lsn = LsnPosition.from_string("0x00000000:00000000:0001")
        await dedup.record(lsn, "dbo.t")
        await dedup.clear()
        result = await dedup.already_applied(lsn, "dbo.t")
        assert result is False

    @pytest.mark.asyncio
    async def test_accepts_string_key(self):
        """Deduplicator accepts a pre-derived string key (e.g. a synthetic
        DedupKey) in addition to an LsnPosition."""
        dedup = Deduplicator()
        await dedup.record("syn:abc123", "dbo.users")
        assert await dedup.already_applied("syn:abc123", "dbo.users") is True
        assert await dedup.already_applied("syn:other", "dbo.users") is False

    @pytest.mark.asyncio
    async def test_with_redis_backend(self):
        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(return_value=b"1")
        dedup = Deduplicator(redis_client=redis_mock)
        lsn = LsnPosition.from_string("0x00001234:0000ABCD:0001")
        result = await dedup.already_applied(lsn, "dbo.users")
        assert result is True
        redis_mock.get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_record_with_redis(self):
        redis_mock = AsyncMock()
        redis_mock.setex = AsyncMock()
        dedup = Deduplicator(redis_client=redis_mock)
        lsn = LsnPosition.from_string("0x00001234:0000ABCD:0001")
        await dedup.record(lsn, "dbo.users")
        redis_mock.setex.assert_awaited_once()
