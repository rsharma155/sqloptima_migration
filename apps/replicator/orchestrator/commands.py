"""
Module: commands.py
Purpose: Change data capture replication pipeline
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from apps.replicator.capture.agent import CaptureAgent
from apps.replicator.orchestrator.models import ReplicationConfig, ReplicationStatus
from apps.replicator.orchestrator.scheduler import Scheduler
from apps.replicator.orchestrator.state_machine import ReplicationEvent, StateMachine

logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    success: bool
    message: str
    data: dict[str, Any] | None = None


_active_replications: dict[str, tuple[StateMachine, ReplicationConfig]] = {}
_capture_agents: dict[str, CaptureAgent] = {}
_scheduler: Scheduler | None = None


def set_scheduler(scheduler: Scheduler) -> None:
    global _scheduler
    _scheduler = scheduler


def register_capture_agent(config_id: str, agent: CaptureAgent) -> None:
    _capture_agents[config_id] = agent


def _get_or_create_state(config_id: str, config: ReplicationConfig | None = None) -> StateMachine:
    if config_id in _active_replications:
        sm, _ = _active_replications[config_id]
        return sm
    if config is None:
        raise ValueError(f"No active replication found for config_id: {config_id}")
    sm = StateMachine()
    _active_replications[config_id] = (sm, config)
    return sm


async def start_replication(
    config_id: str,
    tables: list[str],
    config: ReplicationConfig | None = None,
) -> CommandResult:
    try:
        sm = _get_or_create_state(config_id, config)
        if sm.current_state.value != "IDLE":
            return CommandResult(
                success=False,
                message=(
                    f"Cannot start replication {config_id}: "
                    f"current state is {sm.current_state.value}"
                ),
            )
        sm.transition(ReplicationEvent.START)
        logger.info("Replication %s started for tables: %s", config_id, tables)
        return CommandResult(
            success=True,
            message=f"Replication {config_id} started",
            data={"config_id": config_id, "state": sm.current_state.value, "tables": tables},
        )
    except Exception as e:
        logger.exception("Failed to start replication %s", config_id)
        return CommandResult(success=False, message=str(e))


async def stop_replication(config_id: str) -> CommandResult:
    try:
        if _scheduler is not None:
            try:
                data = await _scheduler.stop_replication(config_id)
                _active_replications.pop(config_id, None)
                _capture_agents.pop(config_id, None)
                return CommandResult(
                    success=True,
                    message=f"Replication {config_id} stopped",
                    data=data,
                )
            except ValueError:
                pass
        sm = _get_or_create_state(config_id)
        if config_id in _capture_agents:
            await _capture_agents[config_id].stop()
        sm.transition(ReplicationEvent.STOP)
        sm.transition(ReplicationEvent.COMPLETE)
        logger.info("Replication %s stopped", config_id)
        _active_replications.pop(config_id, None)
        _capture_agents.pop(config_id, None)
        return CommandResult(
            success=True,
            message=f"Replication {config_id} stopped",
            data={"config_id": config_id, "state": "COMPLETED"},
        )
    except ValueError as e:
        return CommandResult(success=False, message=str(e))
    except Exception as e:
        logger.exception("Failed to stop replication %s", config_id)
        return CommandResult(success=False, message=str(e))


async def pause_replication(config_id: str) -> CommandResult:
    try:
        if _scheduler is not None:
            try:
                data = await _scheduler.pause_replication(config_id)
                return CommandResult(
                    success=True,
                    message=f"Replication {config_id} paused",
                    data=data,
                )
            except ValueError:
                pass
        sm = _get_or_create_state(config_id)
        if config_id in _capture_agents:
            await _capture_agents[config_id].pause()
        sm.transition(ReplicationEvent.PAUSE)
        logger.info("Replication %s paused", config_id)
        return CommandResult(
            success=True,
            message=f"Replication {config_id} paused",
            data={"config_id": config_id, "state": sm.current_state.value},
        )
    except ValueError as e:
        return CommandResult(success=False, message=str(e))
    except Exception as e:
        logger.exception("Failed to pause replication %s", config_id)
        return CommandResult(success=False, message=str(e))


async def resume_replication(config_id: str) -> CommandResult:
    try:
        if _scheduler is not None:
            try:
                data = await _scheduler.resume_replication(config_id)
                return CommandResult(
                    success=True,
                    message=f"Replication {config_id} resumed",
                    data=data,
                )
            except ValueError:
                pass
        sm = _get_or_create_state(config_id)
        if config_id in _capture_agents:
            await _capture_agents[config_id].resume()
        sm.transition(ReplicationEvent.RESUME)
        logger.info("Replication %s resumed", config_id)
        return CommandResult(
            success=True,
            message=f"Replication {config_id} resumed",
            data={"config_id": config_id, "state": sm.current_state.value},
        )
    except ValueError as e:
        return CommandResult(success=False, message=str(e))
    except Exception as e:
        logger.exception("Failed to resume replication %s", config_id)
        return CommandResult(success=False, message=str(e))


async def get_status(config_id: str) -> CommandResult:
    if _scheduler is not None:
        try:
            info = _scheduler.get_replication_status(config_id)
            if info.get("active"):
                return CommandResult(
                    success=True,
                    message=f"Status for {config_id}: {info['state']}",
                    data=info,
                )
        except ValueError:
            pass
    if config_id not in _active_replications:
        return CommandResult(
            success=False,
            message=f"No active replication found for config_id: {config_id}",
        )
    sm, config = _active_replications[config_id]
    progress = {}
    if config_id in _capture_agents:
        progress = _capture_agents[config_id].get_progress()
    status = ReplicationStatus(
        config_id=config_id,
        state=sm.current_state.value,
        started_at=datetime.now(UTC),
        last_heartbeat=datetime.now(UTC),
        events_captured=progress.get("events_captured", 0),
    )
    return CommandResult(
        success=True,
        message=f"Status for {config_id}: {status.state}",
        data=status.model_dump(),
    )


async def schedule_replication(
    config_id: str,
    cron_expression: str,
    scheduler: Scheduler,
    action: Any = None,
) -> CommandResult:
    try:
        if action is None:
            async def default_action() -> None:
                logger.info("Scheduled action triggered for %s", config_id)
            action = default_action
        job_id = scheduler.schedule_cron(config_id, cron_expression, action)
        logger.info("Replication %s scheduled with cron: %s", config_id, cron_expression)
        return CommandResult(
            success=True,
            message=f"Replication {config_id} scheduled with cron: {cron_expression}",
            data={"config_id": config_id, "job_id": job_id, "cron_expression": cron_expression},
        )
    except Exception as e:
        logger.exception("Failed to schedule replication %s", config_id)
        return CommandResult(success=False, message=str(e))
