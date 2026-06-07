"""
Module: state_machine.py
Purpose: Change data capture replication pipeline
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock
from typing import ClassVar

logger = logging.getLogger(__name__)


class ReplicationState(StrEnum):
    IDLE = "IDLE"
    STARTING = "STARTING"
    SNAPSHOTTING = "SNAPSHOTTING"
    CDC_CATCHUP = "CDC_CATCHUP"
    CDC_STREAMING = "CDC_STREAMING"
    PAUSED = "PAUSED"
    STOPPING = "STOPPING"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


class ReplicationEvent(StrEnum):
    START = "START"
    SNAPSHOT_BEGIN = "SNAPSHOT_BEGIN"
    SNAPSHOT_DONE = "SNAPSHOT_DONE"
    CATCHUP_DONE = "CATCHUP_DONE"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    STOP = "STOP"
    FAIL = "FAIL"
    COMPLETE = "COMPLETE"


_TRANSITIONS: dict[ReplicationState, dict[ReplicationEvent, ReplicationState]] = {
    ReplicationState.IDLE: {
        ReplicationEvent.START: ReplicationState.STARTING,
    },
    ReplicationState.STARTING: {
        ReplicationEvent.SNAPSHOT_BEGIN: ReplicationState.SNAPSHOTTING,
        ReplicationEvent.CATCHUP_DONE: ReplicationState.CDC_STREAMING,
        ReplicationEvent.FAIL: ReplicationState.FAILED,
        ReplicationEvent.STOP: ReplicationState.STOPPING,
    },
    ReplicationState.SNAPSHOTTING: {
        ReplicationEvent.SNAPSHOT_DONE: ReplicationState.CDC_CATCHUP,
        ReplicationEvent.FAIL: ReplicationState.FAILED,
        ReplicationEvent.STOP: ReplicationState.STOPPING,
        ReplicationEvent.PAUSE: ReplicationState.PAUSED,
    },
    ReplicationState.CDC_CATCHUP: {
        ReplicationEvent.CATCHUP_DONE: ReplicationState.CDC_STREAMING,
        ReplicationEvent.FAIL: ReplicationState.FAILED,
        ReplicationEvent.STOP: ReplicationState.STOPPING,
        ReplicationEvent.PAUSE: ReplicationState.PAUSED,
    },
    ReplicationState.CDC_STREAMING: {
        ReplicationEvent.FAIL: ReplicationState.FAILED,
        ReplicationEvent.STOP: ReplicationState.STOPPING,
        ReplicationEvent.PAUSE: ReplicationState.PAUSED,
        ReplicationEvent.COMPLETE: ReplicationState.COMPLETED,
    },
    ReplicationState.PAUSED: {
        # Fix 2.4: RESUME target is resolved dynamically from _pre_pause_state;
        # the static table value is intentionally overloaded via StateMachine.transition().
        ReplicationEvent.RESUME: ReplicationState.CDC_STREAMING,  # fallback default
        ReplicationEvent.STOP: ReplicationState.STOPPING,
        ReplicationEvent.FAIL: ReplicationState.FAILED,
    },
    ReplicationState.STOPPING: {
        ReplicationEvent.COMPLETE: ReplicationState.COMPLETED,
        ReplicationEvent.FAIL: ReplicationState.FAILED,
    },
    ReplicationState.FAILED: {},
    ReplicationState.COMPLETED: {},
}


@dataclass
class Transition:
    from_state: ReplicationState
    to_state: ReplicationState
    event: ReplicationEvent
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class StateMachine:
    _VALID_TRANSITIONS: ClassVar[
        dict[ReplicationState, dict[ReplicationEvent, ReplicationState]]
    ] = _TRANSITIONS

    def __init__(self, initial_state: ReplicationState = ReplicationState.IDLE) -> None:
        self._current_state = initial_state
        self._transitions_history: list[Transition] = []
        self._lock = Lock()
        # Fix 2.4: track which state was active before PAUSE so RESUME returns there.
        self._pre_pause_state: ReplicationState | None = None

    @property
    def current_state(self) -> ReplicationState:
        return self._current_state

    @property
    def transitions_history(self) -> list[Transition]:
        return list(self._transitions_history)

    def transition(self, event: ReplicationEvent) -> Transition:
        with self._lock:
            current = self._current_state
            event_map = self._VALID_TRANSITIONS.get(current)
            if event_map is None or event not in event_map:
                allowed = self.allowed_events()
                raise ValueError(
                    f"Invalid transition: {current} --[{event}]--> ?. "
                    f"Allowed events from {current}: {[e.value for e in allowed]}"
                )

            # Fix 2.4: record state before PAUSE; on RESUME restore it instead of
            # unconditionally jumping to CDC_STREAMING.
            if event == ReplicationEvent.PAUSE:
                self._pre_pause_state = current
            elif event == ReplicationEvent.RESUME and self._pre_pause_state is not None:
                # Resume to wherever we were before the pause
                target = self._pre_pause_state
                self._pre_pause_state = None
                t = Transition(from_state=current, to_state=target, event=event)
                self._transitions_history.append(t)
                self._current_state = target
                logger.info(
                    "State transition: %s --[%s]--> %s (restored pre-pause state)",
                    current.value, event.value, target.value,
                )
                return t

            next_state = event_map[event]
            t = Transition(
                from_state=current,
                to_state=next_state,
                event=event,
            )
            self._transitions_history.append(t)
            self._current_state = next_state
            logger.info(
                "State transition: %s --[%s]--> %s",
                current.value, event.value, next_state.value,
            )
            return t

    def allowed_events(self) -> list[ReplicationEvent]:
        event_map = self._VALID_TRANSITIONS.get(self._current_state)
        if event_map is None:
            return []
        return list(event_map.keys())

    def can_transition_to(self, target: ReplicationState) -> bool:
        return any(
            to_state == target
            for to_state in self._VALID_TRANSITIONS.get(self._current_state, {}).values()
        )

    def is_terminal(self) -> bool:
        return self._current_state in (ReplicationState.FAILED, ReplicationState.COMPLETED)
