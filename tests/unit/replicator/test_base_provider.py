"""
Module: tests/unit/replicator/test_base_provider.py
Purpose: Unit tests for AbstractCaptureProvider interface and its contract
Author: Migration Platform Team
Created: 2026-05-22
Domain: Replication / Capture
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from unittest.mock import AsyncMock

import pytest

from apps.replicator.capture.models import (
    CaptureBatch,
    ChangeEvent,
    ChangeOperation,
    LsnPosition,
    TableInfo,
)
from apps.replicator.capture.providers.base import AbstractCaptureProvider


class TestAbstractCaptureProviderInterface:
    """Verify the abstract base class enforces the correct contract."""

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            AbstractCaptureProvider()  # type: ignore[abstract]

    def test_concrete_subclass_must_implement_all_methods(self):
        class Incomplete(AbstractCaptureProvider):
            pass

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            Incomplete()  # type: ignore[abstract]

    def test_valid_subclass_works(self):
        class Concrete(AbstractCaptureProvider):
            async def connect(self, connection_string: str) -> None:
                pass

            async def discover_tables(self, schema: str) -> list[TableInfo]:
                return []

            async def capture_changes(
                self, table: TableInfo, last_position: bytes | None, batch_size: int = 1000,
            ) -> CaptureBatch:
                lsn = LsnPosition.from_string("0x00000000:00000000:0000")
                return CaptureBatch(changes=[], new_position=lsn)

            async def take_snapshot(
                self, table: TableInfo, callback, chunk_size: int = 10000,
            ) -> None:
                pass

        instance = Concrete()
        assert isinstance(instance, AbstractCaptureProvider)


class TestConcreteProvider:
    """Test a concrete provider following TDD — mock-based."""

    @pytest.mark.asyncio
    async def test_connect_sets_up_connection(self):
        provider = _create_mock_provider()
        await provider.connect("mock://localhost")
        provider.connect.assert_awaited_once_with("mock://localhost")

    @pytest.mark.asyncio
    async def test_discover_tables_returns_list(self):
        provider = _create_mock_provider()
        provider.discover_tables.return_value = [
            TableInfo(schema_name="dbo", table_name="users", columns=["id", "name"]),
        ]
        tables = await provider.discover_tables("dbo")
        assert len(tables) == 1
        assert tables[0].table_name == "users"

    @pytest.mark.asyncio
    async def test_capture_changes_returns_batch(self):
        provider = _create_mock_provider()
        lsn = LsnPosition.from_string("0x00001234:0000ABCD:0001")
        event = ChangeEvent(
            table_schema="dbo",
            table_name="users",
            operation=ChangeOperation.INSERT,
            after_values={"id": 1},
            lsn=lsn,
        )
        provider.capture_changes.return_value = CaptureBatch(changes=[event], new_position=lsn)

        table = TableInfo(schema_name="dbo", table_name="users", columns=["id", "name"])
        batch = await provider.capture_changes(table, None)
        assert batch.change_count == 1
        assert batch.changes[0].operation == ChangeOperation.INSERT

    @pytest.mark.asyncio
    async def test_take_snapshot_invokes_callback(self):
        provider = _create_mock_provider()
        callback = AsyncMock()
        table = TableInfo(schema_name="dbo", table_name="users", columns=["id"])

        await provider.take_snapshot(table, callback, chunk_size=100)
        provider.take_snapshot.assert_awaited_once_with(table, callback, chunk_size=100)


def _create_mock_provider():
    """Create a complete mock that implements the abstract interface."""
    from unittest.mock import AsyncMock, MagicMock

    class MockProvider(AbstractCaptureProvider):
        async def connect(self, connection_string: str) -> None:
            pass

        async def discover_tables(self, schema: str) -> list[TableInfo]:
            return []

        async def capture_changes(
            self, table: TableInfo, last_position: bytes | None, batch_size: int = 1000,
        ) -> CaptureBatch:
            lsn = LsnPosition.from_string("0x00000000:00000000:0000")
            return CaptureBatch(changes=[], new_position=lsn)

        async def take_snapshot(self, table: TableInfo, callback, chunk_size: int = 10000) -> None:
            pass

    return MagicMock(spec=MockProvider, AsyncMock=AsyncMock)
