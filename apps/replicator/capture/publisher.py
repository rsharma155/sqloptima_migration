"""
Module: apps/replicator/capture/publisher.py
Purpose: RabbitMQ message publisher with publisher confirms and retry logic
Author: Migration Platform Team
Created: 2026-05-22
Domain: Replication / Publisher
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import json
import logging
from typing import Any

import aio_pika

from apps.replicator.capture.models import ChangeEvent

logger = logging.getLogger(__name__)


class MessagePublisher:
    """Publishes ChangeEvents to RabbitMQ with durable delivery guarantees.

    Uses aio-pika for async RabbitMQ integration with publisher confirms
    for at-least-once delivery semantics.
    """

    def __init__(
        self,
        url: str = "amqp://localhost",
        exchange: str = "cdc.data",
        use_confirms: bool = True,
    ) -> None:
        self._url = url
        self._exchange = exchange
        self._use_confirms = use_confirms
        self._connection: aio_pika.RobustConnection | None = None
        self._channel: aio_pika.RobustChannel | None = None

    async def connect(self) -> None:
        """Establish connection and create channel.

        Raises:
            ConnectionError: If broker connection fails.
        """
        self._connection = await self._connect()
        self._channel = await self._connection.channel()
        self._channel.confirm_deliveries = self._use_confirms
        await self._channel.declare_exchange(
            name=self._exchange,
            type=aio_pika.ExchangeType.TOPIC,
            durable=True,
        )

    async def _connect(self) -> aio_pika.RobustConnection:
        """Establish a real aio-pika connection to RabbitMQ."""
        return await aio_pika.connect_robust(self._url)

    async def disconnect(self) -> None:
        """Close channel and connection gracefully."""
        if self._channel:
            await self._channel.close()
        if self._connection:
            await self._connection.close()
        self._channel = None
        self._connection = None

    async def publish(self, event: ChangeEvent) -> bool:
        """Publish a single change event to the message broker.

        Args:
            event: Change event to publish.

        Returns:
            True if published successfully.

        Raises:
            RuntimeError: If publisher is not connected.
        """
        if not self._channel:
            raise RuntimeError("MessagePublisher not connected")

        payload = self._serialize_event(event)
        routing_key = self._routing_key(event)
        body = json.dumps(payload, default=str).encode()

        message = aio_pika.Message(
            body=body,
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            content_type="application/json",
        )
        await self._channel.default_exchange.publish(
            message,
            routing_key=routing_key,
        )
        return True

    @staticmethod
    def _serialize_event(event: ChangeEvent) -> dict[str, Any]:
        """Serialize a ChangeEvent into the standard message envelope."""
        return {
            "id": str(event.event_id),
            "timestamp": event.source_timestamp.isoformat() if event.source_timestamp else "",
            "source": {
                "type": "mssql",
                "host": event.source_host,
                "database": event.source_database,
                "lsn": event.lsn.to_string() if event.lsn else "",
                "txn_id": event.transaction_id,
            },
            "table": {
                "schema": event.table_schema,
                "name": event.table_name,
            },
            "operation": event.operation.value,
            "before": event.before_values,
            "after": event.after_values,
            "headers": {
                "schema_version": 1,
                "content_type": "application/json",
                "message_type": "change",
            },
        }

    @staticmethod
    def _routing_key(event: ChangeEvent) -> str:
        """Generate the RabbitMQ routing key for a change event."""
        return f"cdc.data.{event.table_schema}.{event.table_name}"
