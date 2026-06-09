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
        target_name_map = {
            t.name: (t.target_table_name or t.name)
            for t in config.tables
        }
        consumer = ReplicationChangeConsumer(
            target_connection,
            target_schema=config.target_schema,
            table_pk_map=pk_map,
            table_target_names=target_name_map,
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

    def apply_capture_settings(self, poll_interval_ms: int, batch_size: int) -> int:
        """Push new poll interval / batch size to every active capture agent."""
        updated = 0
        for runtime in self._streams.values():
            agent = runtime.capture_agent
            if agent is None:
                continue
            agent.set_poll_interval_ms(poll_interval_ms)
            agent.set_batch_size(batch_size)
            updated += 1
        return updated

    def status_payload(self, stream_id: str) -> dict[str, Any]:
        return self._metrics_payload(stream_id, detailed=False)

    def details_payload(self, stream_id: str) -> dict[str, Any]:
        return self._metrics_payload(stream_id, detailed=True)

    def _metrics_payload(self, stream_id: str, *, detailed: bool) -> dict[str, Any]:
        runtime = self._require(stream_id)
        agent = runtime.capture_agent
        consumer = runtime.consumer
        captured = agent.events_captured if agent else 0
        applied = consumer.events_applied if consumer else 0
        queue_depth = runtime.bus.depth if runtime.bus else 0
        applier_stats = dict(consumer._applier.stats) if consumer else {}
        payload: dict[str, Any] = {
            "stream_id": stream_id,
            "is_active": True,
            "is_running": bool(agent and agent._running and not agent._paused),
            "is_paused": bool(agent and agent._paused),
            "state": runtime.state_machine.current_state.value,
            "events_captured": captured,
            "events_applied": applied,
            "queue_depth": queue_depth,
            "pending_lag": max(0, captured - applied),
            "errors": list(runtime.errors),
            "concerns": list(runtime.concerns),
            "started_at": runtime.started_at.isoformat() if runtime.started_at else None,
            "operations": {
                "insert": applier_stats.get("insert", 0),
                "update": applier_stats.get("update", 0),
                "delete": applier_stats.get("delete", 0),
            },
            "duplicates_skipped": applier_stats.get("duplicate", 0),
            "apply_failures": applier_stats.get("failed", 0),
            "batches_polled": agent.batches_polled if agent else 0,
            "batches_with_changes": agent.batches_with_changes if agent else 0,
            "batch_size": agent.batch_size if agent else runtime.config.batch_size,
            "poll_interval_ms": agent.poll_interval_ms if agent else runtime.config.poll_interval_ms,
            "mode": runtime.config.mode,
        }
        if detailed:
            capture_errors = list(agent.capture_errors) if agent else []
            apply_errors = list(consumer._applier.recent_errors) if consumer else []
            payload.update({
                "source_schema": runtime.config.source_schema,
                "target_schema": runtime.config.target_schema,
                "tables": [
                    {
                        "name": t.name,
                        "pk_columns": list(t.pk_columns),
                        "source_qualified": (
                            f"{runtime.config.source_schema}.{t.name}"
                        ),
                        "target_qualified": (
                            f"{runtime.config.target_schema}.{t.name.lower()}"
                        ),
                    }
                    for t in runtime.config.tables
                ],
                "table_progress": list(agent.progress.values()) if agent else [],
                "capture_errors": capture_errors,
                "apply_errors": apply_errors,
                "runtime_errors": list(runtime.errors),
            })
        return payload

    def try_metrics_payload(self, stream_id: str, *, detailed: bool = False) -> dict[str, Any] | None:
        if stream_id not in self._streams:
            return None
        if detailed:
            return self.details_payload(stream_id)
        return self.status_payload(stream_id)

    def _require(self, stream_id: str) -> ActiveStreamRuntime:
        runtime = self._streams.get(stream_id)
        if runtime is None:
            raise ValueError(f"stream {stream_id} is not active")
        return runtime


_runtime_manager = ReplicationRuntimeManager()


def get_runtime_manager() -> ReplicationRuntimeManager:
    return _runtime_manager
