"""
Module: scheduler.py
Purpose: Change data capture replication pipeline
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from apps.replicator.capture.agent import CaptureAgent
from apps.replicator.orchestrator.models import ReplicationConfig
from apps.replicator.orchestrator.state_machine import ReplicationEvent, StateMachine

logger = logging.getLogger(__name__)

JobAction = Callable[[], Any]

ReplicationInfo = dict[str, Any]


class Scheduler:
    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()
        self._job_store: dict[str, dict[str, Any]] = {}
        self._replications: dict[str, ReplicationInfo] = {}

    def schedule_cron(
        self,
        config_id: str,
        cron_expression: str,
        action: JobAction,
        job_id: str | None = None,
    ) -> str:
        jid = job_id or f"cron_{config_id}"
        trigger = CronTrigger.from_crontab(cron_expression)

        def wrapper() -> None:
            logger.info("Job %s started (cron)", jid)
            try:
                action()
                self._job_store[jid]["last_run_time"] = datetime.now(UTC)
                logger.info("Job %s finished successfully", jid)
            except Exception:
                logger.exception("Job %s failed", jid)

        self._scheduler.add_job(wrapper, trigger=trigger, id=jid, replace_existing=True)
        self._job_store[jid] = {
            "id": jid,
            "config_id": config_id,
            "job_type": "cron",
            "cron_expression": cron_expression,
            "action": getattr(action, "__name__", str(action)),
            "status": "scheduled",
            "next_run_time": None,
            "last_run_time": None,
        }
        logger.info("Scheduled cron job %s: %s", jid, cron_expression)
        return jid

    def schedule_interval(
        self,
        config_id: str,
        minutes: int,
        action: JobAction,
        job_id: str | None = None,
    ) -> str:
        jid = job_id or f"interval_{config_id}"
        trigger = IntervalTrigger(minutes=minutes)

        def wrapper() -> None:
            logger.info("Job %s started (interval %d min)", jid, minutes)
            try:
                action()
                self._job_store[jid]["last_run_time"] = datetime.now(UTC)
                logger.info("Job %s finished successfully", jid)
            except Exception:
                logger.exception("Job %s failed", jid)

        self._scheduler.add_job(wrapper, trigger=trigger, id=jid, replace_existing=True)
        self._job_store[jid] = {
            "id": jid,
            "config_id": config_id,
            "job_type": "interval",
            "interval_minutes": minutes,
            "action": getattr(action, "__name__", str(action)),
            "status": "scheduled",
            "next_run_time": None,
            "last_run_time": None,
        }
        logger.info("Scheduled interval job %s: every %d min", jid, minutes)
        return jid

    def schedule_once(
        self,
        config_id: str,
        run_at: datetime,
        action: JobAction,
        job_id: str | None = None,
    ) -> str:
        jid = job_id or f"once_{config_id}"
        trigger = DateTrigger(run_date=run_at)

        def wrapper() -> None:
            logger.info("Job %s started (one-time)", jid)
            try:
                action()
                self._job_store[jid]["last_run_time"] = datetime.now(UTC)
                self._job_store[jid]["status"] = "completed"
                logger.info("Job %s finished successfully", jid)
            except Exception:
                logger.exception("Job %s failed", jid)
                self._job_store[jid]["status"] = "failed"

        self._scheduler.add_job(wrapper, trigger=trigger, id=jid, replace_existing=True)
        self._job_store[jid] = {
            "id": jid,
            "config_id": config_id,
            "job_type": "once",
            "run_at": run_at.isoformat(),
            "action": getattr(action, "__name__", str(action)),
            "status": "scheduled",
            "next_run_time": run_at,
            "last_run_time": None,
        }
        logger.info("Scheduled one-time job %s at %s", jid, run_at.isoformat())
        return jid

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("Scheduler started")

    def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=True)
            logger.info("Scheduler stopped")

    def pause_job(self, job_id: str) -> None:
        self._scheduler.pause_job(job_id)
        if job_id in self._job_store:
            self._job_store[job_id]["status"] = "paused"
        logger.info("Job %s paused", job_id)

    def resume_job(self, job_id: str) -> None:
        self._scheduler.resume_job(job_id)
        if job_id in self._job_store:
            self._job_store[job_id]["status"] = "scheduled"
        logger.info("Job %s resumed", job_id)

    def list_jobs(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for aps_job in self._scheduler.get_jobs():
            meta = self._job_store.get(aps_job.id, {})
            results.append({
                "id": aps_job.id,
                "config_id": meta.get("config_id", ""),
                "job_type": meta.get("job_type", ""),
                "action": meta.get("action", ""),
                "status": meta.get("status", "unknown"),
                "next_run_time": (
                    aps_job.next_run_time.isoformat() if aps_job.next_run_time else None
                ),
                "last_run_time": meta.get("last_run_time"),
                "cron_expression": meta.get("cron_expression"),
                "interval_minutes": meta.get("interval_minutes"),
            })
        return results

    def register_replication(
        self,
        config_id: str,
        capture_agent: CaptureAgent,
        state_machine: StateMachine,
        config: ReplicationConfig | None = None,
    ) -> None:
        self._replications[config_id] = {
            "capture_agent": capture_agent,
            "state_machine": state_machine,
            "config": config,
        }
        logger.info("Registered replication %s", config_id)

    def _get_replication(self, config_id: str) -> ReplicationInfo:
        if config_id not in self._replications:
            raise ValueError(f"No replication registered for config_id: {config_id}")
        return self._replications[config_id]

    async def pause_replication(self, config_id: str) -> dict[str, Any]:
        info = self._get_replication(config_id)
        agent: CaptureAgent = info["capture_agent"]
        sm: StateMachine = info["state_machine"]
        await agent.pause()
        sm.transition(ReplicationEvent.PAUSE)
        logger.info("Replication %s paused via scheduler", config_id)
        return {"config_id": config_id, "state": sm.current_state.value}

    async def resume_replication(self, config_id: str) -> dict[str, Any]:
        info = self._get_replication(config_id)
        agent: CaptureAgent = info["capture_agent"]
        sm: StateMachine = info["state_machine"]
        await agent.resume()
        sm.transition(ReplicationEvent.RESUME)
        logger.info("Replication %s resumed via scheduler", config_id)
        return {"config_id": config_id, "state": sm.current_state.value}

    async def stop_replication(self, config_id: str) -> dict[str, Any]:
        info = self._get_replication(config_id)
        agent: CaptureAgent = info["capture_agent"]
        sm: StateMachine = info["state_machine"]
        await agent.stop()
        sm.transition(ReplicationEvent.STOP)
        sm.transition(ReplicationEvent.COMPLETE)
        self._replications.pop(config_id, None)
        logger.info("Replication %s stopped via scheduler", config_id)
        return {"config_id": config_id, "state": "COMPLETED"}

    def get_replication_status(self, config_id: str) -> dict[str, Any]:
        if config_id not in self._replications:
            return {"config_id": config_id, "active": False}
        info = self._replications[config_id]
        agent: CaptureAgent = info["capture_agent"]
        sm: StateMachine = info["state_machine"]
        progress = agent.get_progress()
        return {
            "config_id": config_id,
            "active": True,
            "state": sm.current_state.value,
            "running": progress["running"],
            "paused": progress["paused"],
            "events_captured": progress["events_captured"],
            "tables": progress["tables"],
            "tables_count": progress["tables_count"],
        }

