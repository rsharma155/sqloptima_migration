"""
Module: tests/unit/replicator/test_publisher.py
Purpose: Unit tests for RabbitMQ message publisher with confirms
Author: Migration Platform Team
Created: 2026-05-22
Domain: Replication / Publisher
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.replicator.capture.models import ChangeEvent, ChangeOperation, LsnPosition
from apps.replicator.capture.publisher import MessagePublisher


@pytest.fixture
def event():
    return ChangeEvent(
        table_schema="dbo",
        table_name="users",
        operation=ChangeOperation.INSERT,
        after_values={"id": 1, "name": "Alice"},
        lsn=LsnPosition.from_string("0x00001234:0000ABCD:0001"),
        source_host="sql-01",
        source_database="salesdb",
    )


class TestMessagePublisher:
    @pytest.mark.asyncio
    async def test_connect_creates_connection(self):
        publisher = MessagePublisher(url="amqp://localhost")
        publisher._connect = AsyncMock()
        await publisher.connect()
        publisher._connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_closes_connection(self):
        publisher = MessagePublisher(url="amqp://localhost")
        channel = MagicMock()
        channel.close = AsyncMock()
        connection = MagicMock()
        connection.close = AsyncMock()
        publisher._channel = channel
        publisher._connection = connection
        await publisher.disconnect()
        channel.close.assert_awaited_once()
        connection.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_publish_sends_message(self, event):
        publisher = MessagePublisher(url="amqp://localhost")
        publisher._channel = AsyncMock()

        result = await publisher.publish(event)
        assert result is True
        # publish() routes through the channel's default_exchange (aio-pika API),
        # not the low-level basic_publish.
        publisher._channel.default_exchange.publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_publish_without_channel_raises(self, event):
        publisher = MessagePublisher(url="amqp://localhost")
        publisher._channel = None
        with pytest.raises(RuntimeError, match="not connected"):
            await publisher.publish(event)

    def test_serialize_event_contains_required_fields(self, event):
        payload = MessagePublisher._serialize_event(event)
        assert payload["operation"] == "INSERT"
        assert payload["table"]["schema"] == "dbo"
        assert payload["table"]["name"] == "users"
        assert payload["source"]["lsn"] == "0x00001234:0000ABCD:0001"
        assert payload["source"]["host"] == "sql-01"
        assert "id" in payload["after"]
        assert payload["headers"]["message_type"] == "change"

    def test_serialize_event_delete_no_after(self):
        event = ChangeEvent(
            table_schema="dbo",
            table_name="orders",
            operation=ChangeOperation.DELETE,
            before_values={"id": 99},
        )
        payload = MessagePublisher._serialize_event(event)
        assert payload["operation"] == "DELETE"
        assert payload["after"] is None
        assert payload["before"]["id"] == 99

    def test_routing_key_format(self, event):
        key = MessagePublisher._routing_key(event)
        assert key == "cdc.data.dbo.users"

    @pytest.mark.asyncio
    async def test_publish_with_confirm(self, event):
        publisher = MessagePublisher(url="amqp://localhost", use_confirms=True)
        publisher._channel = AsyncMock()
        publisher._channel.basic_publish = AsyncMock()

        result = await publisher.publish(event)
        assert result is True
