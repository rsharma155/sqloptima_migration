"""
Module: test_scheduler.py
Purpose: Unit tests
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from asyncio import sleep
from datetime import UTC, datetime, timedelta

import pytest

from apps.replicator.orchestrator.commands import (
    CommandResult,
    get_status,
    pause_replication,
    resume_replication,
    start_replication,
    stop_replication,
)
from apps.replicator.orchestrator.models import ReplicationConfig
from apps.replicator.orchestrator.scheduler import Scheduler
from apps.replicator.orchestrator.state_machine import (
    ReplicationEvent,
    ReplicationState,
    StateMachine,
    Transition,
)


class TestStateMachine:
    def test_initial_state_is_idle(self):
        sm = StateMachine()
        assert sm.current_state == ReplicationState.IDLE

    def test_valid_transition_idle_to_starting(self):
        sm = StateMachine()
        t = sm.transition(ReplicationEvent.START)
        assert sm.current_state == ReplicationState.STARTING
        assert isinstance(t, Transition)
        assert t.from_state == ReplicationState.IDLE
        assert t.to_state == ReplicationState.STARTING
        assert t.event == ReplicationEvent.START

    def test_valid_transition_full_cycle(self):
        sm = StateMachine()
        sm.transition(ReplicationEvent.START)
        sm.transition(ReplicationEvent.SNAPSHOT_BEGIN)
        assert sm.current_state == ReplicationState.SNAPSHOTTING
        sm.transition(ReplicationEvent.SNAPSHOT_DONE)
        assert sm.current_state == ReplicationState.CDC_CATCHUP
        sm.transition(ReplicationEvent.CATCHUP_DONE)
        assert sm.current_state == ReplicationState.CDC_STREAMING
        sm.transition(ReplicationEvent.COMPLETE)
        assert sm.current_state == ReplicationState.COMPLETED

    def test_valid_transition_starting_to_cdc_directly(self):
        sm = StateMachine()
        sm.transition(ReplicationEvent.START)
        sm.transition(ReplicationEvent.CATCHUP_DONE)
        assert sm.current_state == ReplicationState.CDC_STREAMING

    def test_valid_transition_pause_resume(self):
        # Fix 2.4: RESUME must restore the pre-pause state, not jump to CDC_STREAMING.
        sm = StateMachine()
        sm.transition(ReplicationEvent.START)
        sm.transition(ReplicationEvent.SNAPSHOT_BEGIN)
        sm.transition(ReplicationEvent.PAUSE)
        assert sm.current_state == ReplicationState.PAUSED
        sm.transition(ReplicationEvent.RESUME)
        # Pre-pause state was SNAPSHOTTING, so resume returns there.
        assert sm.current_state == ReplicationState.SNAPSHOTTING

    def test_invalid_transition_raises_value_error(self):
        sm = StateMachine()
        with pytest.raises(ValueError, match="Invalid transition"):
            sm.transition(ReplicationEvent.CATCHUP_DONE)

    def test_invalid_transition_from_idle_to_cdc_streaming(self):
        sm = StateMachine()
        with pytest.raises(ValueError, match="Invalid transition"):
            sm.transition(ReplicationEvent.CATCHUP_DONE)

    def test_invalid_transition_from_terminal_state(self):
        sm = StateMachine()
        sm.transition(ReplicationEvent.START)
        sm.transition(ReplicationEvent.FAIL)
        assert sm.current_state == ReplicationState.FAILED
        with pytest.raises(ValueError):
            sm.transition(ReplicationEvent.START)

    def test_allowed_events_from_idle(self):
        sm = StateMachine()
        events = sm.allowed_events()
        assert ReplicationEvent.START in events
        assert len(events) == 1

    def test_allowed_events_from_streaming(self):
        sm = StateMachine()
        sm.transition(ReplicationEvent.START)
        sm.transition(ReplicationEvent.SNAPSHOT_BEGIN)
        sm.transition(ReplicationEvent.SNAPSHOT_DONE)
        sm.transition(ReplicationEvent.CATCHUP_DONE)
        events = sm.allowed_events()
        assert ReplicationEvent.FAIL in events
        assert ReplicationEvent.STOP in events
        assert ReplicationEvent.PAUSE in events
        assert ReplicationEvent.COMPLETE in events

    def test_allowed_events_from_failed(self):
        sm = StateMachine()
        sm.transition(ReplicationEvent.START)
        sm.transition(ReplicationEvent.FAIL)
        assert sm.allowed_events() == []

    def test_can_transition_to_true(self):
        sm = StateMachine()
        assert sm.can_transition_to(ReplicationState.STARTING) is True
        assert sm.can_transition_to(ReplicationState.CDC_STREAMING) is False

    def test_can_transition_to_false(self):
        sm = StateMachine()
        assert sm.can_transition_to(ReplicationState.FAILED) is False

    def test_is_terminal_for_failed(self):
        sm = StateMachine()
        sm.transition(ReplicationEvent.START)
        sm.transition(ReplicationEvent.FAIL)
        assert sm.is_terminal() is True

    def test_is_terminal_for_completed(self):
        sm = StateMachine()
        sm.transition(ReplicationEvent.START)
        sm.transition(ReplicationEvent.SNAPSHOT_BEGIN)
        sm.transition(ReplicationEvent.SNAPSHOT_DONE)
        sm.transition(ReplicationEvent.CATCHUP_DONE)
        sm.transition(ReplicationEvent.COMPLETE)
        assert sm.is_terminal() is True

    def test_is_terminal_for_idle(self):
        sm = StateMachine()
        assert sm.is_terminal() is False

    def test_transitions_history_tracks_all(self):
        sm = StateMachine()
        sm.transition(ReplicationEvent.START)
        sm.transition(ReplicationEvent.SNAPSHOT_BEGIN)
        sm.transition(ReplicationEvent.SNAPSHOT_DONE)
        assert len(sm.transitions_history) == 3
        assert sm.transitions_history[0].event == ReplicationEvent.START
        assert sm.transitions_history[1].event == ReplicationEvent.SNAPSHOT_BEGIN
        assert sm.transitions_history[2].event == ReplicationEvent.SNAPSHOT_DONE

    def test_allowed_events_no_mutation(self):
        sm = StateMachine()
        allowed = sm.allowed_events()
        assert len(allowed) == 1
        sm.transition(ReplicationEvent.START)
        assert len(sm.allowed_events()) == 4

    def test_fail_from_cdc_streaming(self):
        sm = StateMachine()
        sm.transition(ReplicationEvent.START)
        sm.transition(ReplicationEvent.CATCHUP_DONE)
        sm.transition(ReplicationEvent.FAIL)
        assert sm.current_state == ReplicationState.FAILED

    def test_stop_from_cdc_catchup(self):
        sm = StateMachine()
        sm.transition(ReplicationEvent.START)
        sm.transition(ReplicationEvent.SNAPSHOT_BEGIN)
        sm.transition(ReplicationEvent.SNAPSHOT_DONE)
        sm.transition(ReplicationEvent.STOP)
        assert sm.current_state == ReplicationState.STOPPING
        sm.transition(ReplicationEvent.COMPLETE)
        assert sm.current_state == ReplicationState.COMPLETED

    def test_pause_from_snapshotting(self):
        sm = StateMachine()
        sm.transition(ReplicationEvent.START)
        sm.transition(ReplicationEvent.SNAPSHOT_BEGIN)
        sm.transition(ReplicationEvent.PAUSE)
        assert sm.current_state == ReplicationState.PAUSED

    def test_fail_from_snapshotting(self):
        sm = StateMachine()
        sm.transition(ReplicationEvent.START)
        sm.transition(ReplicationEvent.SNAPSHOT_BEGIN)
        sm.transition(ReplicationEvent.FAIL)
        assert sm.current_state == ReplicationState.FAILED

    def test_stop_from_starting(self):
        sm = StateMachine()
        sm.transition(ReplicationEvent.START)
        sm.transition(ReplicationEvent.STOP)
        assert sm.current_state == ReplicationState.STOPPING

    def test_allowed_events_from_stopping(self):
        sm = StateMachine()
        sm.transition(ReplicationEvent.START)
        sm.transition(ReplicationEvent.STOP)
        events = sm.allowed_events()
        assert ReplicationEvent.COMPLETE in events
        assert ReplicationEvent.FAIL in events
        assert len(events) == 2

    def test_allowed_events_from_paused(self):
        sm = StateMachine()
        sm.transition(ReplicationEvent.START)
        sm.transition(ReplicationEvent.CATCHUP_DONE)
        sm.transition(ReplicationEvent.PAUSE)
        events = sm.allowed_events()
        assert ReplicationEvent.RESUME in events
        assert ReplicationEvent.STOP in events
        assert ReplicationEvent.FAIL in events


class TestScheduler:
    @pytest.mark.asyncio
    async def test_scheduler_start_stop(self):
        sched = Scheduler()
        sched.start()
        sched.schedule_interval("cfg-x", 5, lambda: None, job_id="test-job-stop")
        jobs_before = sched.list_jobs()
        assert len(jobs_before) == 1
        sched.stop()

    @pytest.mark.asyncio
    async def test_scheduler_double_start_is_idempotent(self):
        sched = Scheduler()
        sched.start()
        sched.start()
        sched.stop()

    @pytest.mark.asyncio
    async def test_schedule_cron_job(self):
        sched = Scheduler()
        sched.start()
        called = False

        def action():
            nonlocal called
            called = True

        jid = sched.schedule_cron("cfg-1", "* * * * *", action)
        jobs = sched.list_jobs()
        assert any(j["id"] == jid for j in jobs)
        assert jid.startswith("cron_cfg-1")
        sched.stop()

    @pytest.mark.asyncio
    async def test_schedule_interval_job(self):
        sched = Scheduler()
        sched.start()
        called = False

        def action():
            nonlocal called
            called = True

        jid = sched.schedule_interval("cfg-2", 5, action)
        jobs = sched.list_jobs()
        match = [j for j in jobs if j["id"] == jid]
        assert len(match) == 1
        assert match[0]["job_type"] == "interval"
        assert match[0]["interval_minutes"] == 5
        sched.stop()

    @pytest.mark.asyncio
    async def test_schedule_once_job(self):
        sched = Scheduler()
        sched.start()
        called = False

        def action():
            nonlocal called
            called = True

        run_at = datetime.now(UTC) + timedelta(seconds=1)
        jid = sched.schedule_once("cfg-3", run_at, action)
        jobs = sched.list_jobs()
        match = [j for j in jobs if j["id"] == jid]
        assert len(match) == 1
        assert match[0]["job_type"] == "once"
        sched.stop()

    @pytest.mark.asyncio
    async def test_scheduler_pause_resume(self):
        sched = Scheduler()
        sched.start()

        def action():
            pass

        jid = sched.schedule_interval("cfg-4", 10, action)
        sched.pause_job(jid)
        jobs = sched.list_jobs()
        paused = [j for j in jobs if j["id"] == jid]
        assert paused[0]["status"] == "paused"

        sched.resume_job(jid)
        jobs = sched.list_jobs()
        resumed = [j for j in jobs if j["id"] == jid]
        assert resumed[0]["status"] == "scheduled"
        sched.stop()

    @pytest.mark.asyncio
    async def test_scheduler_list_jobs(self):
        sched = Scheduler()
        sched.start()

        def action():
            pass

        sched.schedule_cron("cfg-a", "*/5 * * * *", action, job_id="job-cron")
        sched.schedule_interval("cfg-b", 15, action, job_id="job-int")
        run_at = datetime.now(UTC) + timedelta(hours=1)
        sched.schedule_once("cfg-c", run_at, action, job_id="job-once")

        jobs = sched.list_jobs()
        ids = [j["id"] for j in jobs]
        assert "job-cron" in ids
        assert "job-int" in ids
        assert "job-once" in ids
        assert len(jobs) == 3
        sched.stop()

    @pytest.mark.asyncio
    async def test_scheduler_interval_job_runs(self):
        sched = Scheduler()
        sched.start()
        call_count = 0

        def action():
            nonlocal call_count
            call_count += 1

        sched.schedule_interval("cfg-5", 1/60, action)
        await sleep(1.5)
        assert call_count >= 1
        sched.stop()
        sched.stop()

    @pytest.mark.asyncio
    async def test_scheduler_cron_with_custom_job_id(self):
        sched = Scheduler()
        sched.start()

        def action():
            pass

        jid = sched.schedule_cron("cfg-6", "0 * * * *", action, job_id="my-cron-job")
        assert jid == "my-cron-job"
        jobs = sched.list_jobs()
        assert any(j["id"] == "my-cron-job" for j in jobs)
        sched.stop()


class TestCommands:
    @pytest.mark.asyncio
    async def test_start_replication_command(self):
        config = ReplicationConfig(
            id="test-1",
            name="Test Config",
            source_conn={"host": "src"},
            target_conn={"host": "tgt"},
            tables=["users"],
        )
        result = await start_replication("test-1", ["users"], config)
        assert result.success is True
        assert "started" in result.message
        assert result.data is not None
        assert result.data["config_id"] == "test-1"

    @pytest.mark.asyncio
    async def test_start_replication_already_running(self):
        config = ReplicationConfig(
            id="test-2",
            name="Test Config 2",
            source_conn={"host": "src"},
            target_conn={"host": "tgt"},
            tables=["orders"],
        )
        result1 = await start_replication("test-2", ["orders"], config)
        assert result1.success is True
        result2 = await start_replication("test-2", ["orders"])
        assert result2.success is False
        assert "Cannot start" in result2.message

    @pytest.mark.asyncio
    async def test_stop_replication_command(self):
        config = ReplicationConfig(
            id="test-3",
            name="Test Config 3",
            source_conn={"host": "src"},
            target_conn={"host": "tgt"},
            tables=["items"],
        )
        await start_replication("test-3", ["items"], config)
        result = await stop_replication("test-3")
        assert result.success is True
        assert "stopped" in result.message

    @pytest.mark.asyncio
    async def test_pause_resume_replication(self):
        config = ReplicationConfig(
            id="test-4",
            name="Test Config 4",
            source_conn={"host": "src"},
            target_conn={"host": "tgt"},
            tables=["products"],
        )
        await start_replication("test-4", ["products"], config)
        from apps.replicator.orchestrator.commands import _active_replications
        from apps.replicator.orchestrator.state_machine import ReplicationEvent
        sm, _ = _active_replications["test-4"]
        sm.transition(ReplicationEvent.SNAPSHOT_BEGIN)
        pause_result = await pause_replication("test-4")
        assert pause_result.success is True
        assert "paused" in pause_result.message

        resume_result = await resume_replication("test-4")
        assert resume_result.success is True
        assert "resumed" in resume_result.message

    @pytest.mark.asyncio
    async def test_get_status_command(self):
        config = ReplicationConfig(
            id="test-5",
            name="Test Config 5",
            source_conn={"host": "src"},
            target_conn={"host": "tgt"},
            tables=["logs"],
        )
        await start_replication("test-5", ["logs"], config)
        result = await get_status("test-5")
        assert result.success is True
        assert result.data is not None
        assert result.data["config_id"] == "test-5"
        assert "state" in result.data

    @pytest.mark.asyncio
    async def test_get_status_not_found(self):
        result = await get_status("non-existent")
        assert result.success is False
        assert "No active" in result.message

    @pytest.mark.asyncio
    async def test_stop_replication_not_started(self):
        result = await stop_replication("never-started")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_pause_replication_not_started(self):
        result = await pause_replication("never-started-pause")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_resume_replication_not_started(self):
        result = await resume_replication("never-started-resume")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_start_replication_command_result_type(self):
        config = ReplicationConfig(
            id="test-type",
            name="Type Test",
            source_conn={"host": "src"},
            target_conn={"host": "tgt"},
            tables=["t"],
        )
        result = await start_replication("test-type", ["t"], config)
        assert isinstance(result, CommandResult)
        assert isinstance(result.success, bool)
        assert isinstance(result.message, str)

    @pytest.mark.asyncio
    async def test_schedule_replication_command(self):
        sched = Scheduler()
        sched.start()
        called = False

        def action():
            nonlocal called
            called = True

        result = await _call_schedule("sched-cfg", "0 * * * *", sched, action)
        assert result.success is True
        assert "scheduled" in result.message
        sched.stop()


async def _call_schedule(config_id, cron_expr, scheduler, action):
    from apps.replicator.orchestrator.commands import schedule_replication
    return await schedule_replication(config_id, cron_expr, scheduler, action)
