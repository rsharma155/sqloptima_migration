"""
Module: replication_runtime.py
Purpose: In-process replication runtime — capture, queue, apply, pause/resume/stop
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from apps.replicator.capture.agent import CaptureAgent
from apps.replicator.capture.models import TableInfo
from apps.replicator.capture.providers.base import AbstractCaptureProvider
from apps.replicator.orchestrator.state_machine import ReplicationEvent, StateMachine
from domains.replication.entities import ReplicationStreamConfig
from infrastructure.replication.capture_provider_factory import ConfiguredWatermarkProvider
from infrastructure.replication.change_consumer import ReplicationChangeConsumer
from infrastructure.replication.message_bus import (
    InMemoryChangeBus,
    LoopbackPublisher,
    RabbitMqBridgeConsumer,
)
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


@dataclass
class ActiveStreamRuntime:
    stream_id: str
    config: ReplicationStreamConfig
    state_machine: StateMachine
    capture_agent: CaptureAgent | None = None
    bus: InMemoryChangeBus | None = None
    consumer: ReplicationChangeConsumer | None = None
    rabbit_consumer: RabbitMqBridgeConsumer | None = None
    heartbeat_task: asyncio.Task | None = None
    started_at: datetime | None = None
    errors: list[str] = field(default_factory=list)
    concerns: list[dict[str, Any]] = field(default_factory=list)


class ReplicationRuntimeManager:
    """Manages active replication streams in the API process."""

    def __init__(self) -> None:
        self._streams: dict[str, ActiveStreamRuntime] = {}

    def get(self, stream_id: str) -> ActiveStreamRuntime | None:
        return self._streams.get(stream_id)

    def list_active_ids(self) -> list[str]:
        return list(self._streams.keys())

    async def start_stream(
        self,
        config: ReplicationStreamConfig,
        *,
        provider: AbstractCaptureProvider | None = None,
        target_connection: Any | None = None,
        table_infos: list[TableInfo] | None = None,
    ) -> ActiveStreamRuntime:
        if config.stream_id in self._streams:
            raise ValueError(f"stream {config.stream_id} is already active")

        sm = StateMachine()
        sm.transition(ReplicationEvent.START)
        sm.transition(ReplicationEvent.CATCHUP_DONE)

        runtime = ActiveStreamRuntime(
            stream_id=config.stream_id,
            config=config,
            state_machine=sm,
            started_at=datetime.now(UTC),
        )
        self._streams[config.stream_id] = runtime

        if target_connection is None:
            runtime.errors.append("target connection unavailable — stream registered only")
            logger.warning("replication_start_degraded", stream_id=config.stream_id)
            return runtime

        bus = InMemoryChangeBus(maxsize=int(os.environ.get("REPLICATION_QUEUE_SIZE", "2000")))
        publisher = LoopbackPublisher(bus)
        await publisher.connect()

        pk_map = {t.name: t.pk_columns for t in config.tables}
        consumer = ReplicationChangeConsumer(
            target_connection,
            target_schema=config.target_schema,
            table_pk_map=pk_map,
        )
        await bus.start(consumer.handle)

        if provider is None:
            infos = table_infos or [
                TableInfo(
                    schema_name=config.source_schema,
                    table_name=t.name,
                    columns=["*"],
                    pk_columns=t.pk_columns or ["id"],
                    watermark_column=t.watermark_column or "modified",
                    soft_delete_column=t.soft_delete_column,
                )
                for t in config.tables
            ]
            provider = ConfiguredWatermarkProvider(infos)

        agent = CaptureAgent(
            provider=provider,
            publisher=publisher,  # type: ignore[arg-type]
            poll_interval_ms=config.poll_interval_ms,
            batch_size=config.batch_size,
        )
        runtime.capture_agent = agent
        runtime.bus = bus
        runtime.consumer = consumer

        rabbit_url = os.environ.get("REPLICATION_RABBITMQ_URL", "").strip()
        if rabbit_url:
            rabbit = RabbitMqBridgeConsumer(
                rabbit_url,
                consumer.handle,
                target_schema=config.target_schema,
            )
            await rabbit.start()
            runtime.rabbit_consumer = rabbit

        table_names = [t.name for t in config.tables]
        await agent.start(config.source_schema, table_names=table_names)
        logger.info(
            "replication_stream_started",
            stream_id=config.stream_id,
            tables=table_names,
            target_schema=config.target_schema,
        )
        return runtime

    async def pause_stream(self, stream_id: str) -> None:
        runtime = self._require(stream_id)
        if runtime.capture_agent:
            await runtime.capture_agent.pause()
        runtime.state_machine.transition(ReplicationEvent.PAUSE)
        logger.info("replication_stream_paused", stream_id=stream_id)

    async def resume_stream(self, stream_id: str) -> None:
        runtime = self._require(stream_id)
        if runtime.capture_agent:
            await runtime.capture_agent.resume()
        runtime.state_machine.transition(ReplicationEvent.RESUME)
        logger.info("replication_stream_resumed", stream_id=stream_id)

    async def stop_stream(self, stream_id: str) -> None:
        runtime = self._streams.get(stream_id)
        if runtime is None:
            return
        with contextlib.suppress(ValueError):
            runtime.state_machine.transition(ReplicationEvent.STOP)
        if runtime.capture_agent:
            await runtime.capture_agent.stop()
        if runtime.bus:
            await runtime.bus.stop()
        if runtime.rabbit_consumer:
            await runtime.rabbit_consumer.stop()
        with contextlib.suppress(ValueError):
            runtime.state_machine.transition(ReplicationEvent.COMPLETE)
        self._streams.pop(stream_id, None)
        logger.info("replication_stream_stopped", stream_id=stream_id)

    async def stop_all(self) -> None:
        for stream_id in list(self._streams.keys()):
            await self.stop_stream(stream_id)

    def status_payload(self, stream_id: str) -> dict[str, Any]:
        runtime = self._require(stream_id)
        captured = runtime.capture_agent.events_captured if runtime.capture_agent else 0
        applied = runtime.consumer.events_applied if runtime.consumer else 0
        queue_depth = runtime.bus.depth if runtime.bus else 0
        return {
            "stream_id": stream_id,
            "state": runtime.state_machine.current_state.value,
            "events_captured": captured,
            "events_applied": applied,
            "queue_depth": queue_depth,
            "errors": list(runtime.errors),
            "concerns": list(runtime.concerns),
            "started_at": runtime.started_at.isoformat() if runtime.started_at else None,
        }

    def _require(self, stream_id: str) -> ActiveStreamRuntime:
        runtime = self._streams.get(stream_id)
        if runtime is None:
            raise ValueError(f"stream {stream_id} is not active")
        return runtime


_runtime_manager = ReplicationRuntimeManager()


def get_runtime_manager() -> ReplicationRuntimeManager:
    return _runtime_manager
