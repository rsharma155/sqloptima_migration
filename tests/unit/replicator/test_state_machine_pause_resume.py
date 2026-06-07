"""
Module: tests/unit/replicator/test_state_machine_pause_resume.py
Purpose: TDD tests for DBA feedback fix 2.4 — PAUSED state must resume to
         the pre-pause state, not unconditionally to CDC_STREAMING.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import pytest

from apps.replicator.orchestrator.state_machine import (
    ReplicationEvent,
    ReplicationState,
    StateMachine,
)


class TestPausedResumePreservesState:
    """
    Issue 2.4: PAUSED → RESUME must restore the pre-pause state, not jump
    unconditionally to CDC_STREAMING.
    """

    def test_pause_during_snapshotting_resumes_to_snapshotting(self):
        sm = StateMachine()
        sm.transition(ReplicationEvent.START)
        sm.transition(ReplicationEvent.SNAPSHOT_BEGIN)
        assert sm.current_state == ReplicationState.SNAPSHOTTING
        sm.transition(ReplicationEvent.PAUSE)
        sm.transition(ReplicationEvent.RESUME)
        assert sm.current_state == ReplicationState.SNAPSHOTTING, (
            "Resuming from SNAPSHOTTING pause must return to SNAPSHOTTING, "
            f"not {sm.current_state}"
        )

    def test_pause_during_cdc_catchup_resumes_to_cdc_catchup(self):
        sm = StateMachine()
        sm.transition(ReplicationEvent.START)
        sm.transition(ReplicationEvent.SNAPSHOT_BEGIN)
        sm.transition(ReplicationEvent.SNAPSHOT_DONE)
        assert sm.current_state == ReplicationState.CDC_CATCHUP
        sm.transition(ReplicationEvent.PAUSE)
        sm.transition(ReplicationEvent.RESUME)
        assert sm.current_state == ReplicationState.CDC_CATCHUP, (
            f"Expected CDC_CATCHUP after resume, got {sm.current_state}"
        )

    def test_pause_during_cdc_streaming_resumes_to_cdc_streaming(self):
        sm = StateMachine()
        sm.transition(ReplicationEvent.START)
        sm.transition(ReplicationEvent.CATCHUP_DONE)
        assert sm.current_state == ReplicationState.CDC_STREAMING
        sm.transition(ReplicationEvent.PAUSE)
        sm.transition(ReplicationEvent.RESUME)
        assert sm.current_state == ReplicationState.CDC_STREAMING

    def test_pre_pause_state_cleared_after_resume(self):
        """After resume, a second pause/resume must track the new pre-pause state."""
        sm = StateMachine()
        sm.transition(ReplicationEvent.START)
        sm.transition(ReplicationEvent.SNAPSHOT_BEGIN)
        sm.transition(ReplicationEvent.PAUSE)
        sm.transition(ReplicationEvent.RESUME)
        # Now in SNAPSHOTTING; complete snapshot
        sm.transition(ReplicationEvent.SNAPSHOT_DONE)  # → CDC_CATCHUP
        sm.transition(ReplicationEvent.CATCHUP_DONE)    # → CDC_STREAMING
        sm.transition(ReplicationEvent.PAUSE)
        sm.transition(ReplicationEvent.RESUME)
        # Should be back in CDC_STREAMING, not SNAPSHOTTING from first pause
        assert sm.current_state == ReplicationState.CDC_STREAMING

    def test_stop_still_works_from_paused(self):
        """STOP must still be valid from PAUSED regardless of pre-pause state."""
        sm = StateMachine()
        sm.transition(ReplicationEvent.START)
        sm.transition(ReplicationEvent.SNAPSHOT_BEGIN)
        sm.transition(ReplicationEvent.PAUSE)
        t = sm.transition(ReplicationEvent.STOP)
        assert t.to_state == ReplicationState.STOPPING
