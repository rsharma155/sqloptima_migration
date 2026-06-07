"""
Module: infrastructure/temporal/client.py
Purpose: Temporal.io client and worker initialization
Author: Migration Platform Team
Created: 2026-05-22
Domain: Infrastructure
Dependencies: temporalio
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

import asyncio
from datetime import timedelta
from typing import Any

from temporalio.client import Client as TemporalClient
from temporalio.runtime import PrometheusConfig, Runtime, TelemetryConfig
from temporalio.worker import Worker

from domains.orchestration import activities as migration_activities
from domains.orchestration.workflows import (
    CutoverWorkflow,
    FullMigrationWorkflow,
    PeriodicValidationWorkflow,
    ReplicationMonitoringWorkflow,
)
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


class TemporalClientFactory:
    """Creates and configures Temporal clients."""

    @staticmethod
    async def create(
        host: str = "localhost",
        port: int = 7233,
        namespace: str = "default",
        use_tls: bool = False,
        enable_metrics: bool = False,
    ) -> TemporalClient:
        """Create a Temporal client connection."""
        runtime: Runtime | None = None
        if enable_metrics:
            runtime = Runtime(
                telemetry=TelemetryConfig(
                    metrics=PrometheusConfig(bind_address="0.0.0.0:9000")
                )
            )

        client = await TemporalClient.connect(
            f"{host}:{port}",
            namespace=namespace,
            runtime=runtime,
            tls=use_tls,
            retry_policy={
                "initial_interval": timedelta(seconds=1),
                "maximum_interval": timedelta(seconds=60),
                "maximum_attempts": 5,
            },
        )
        return client


class TemporalWorkerService:
    """Manages Temporal workers for migration workflows."""

    WORKFLOWS = [
        FullMigrationWorkflow,
        CutoverWorkflow,
        PeriodicValidationWorkflow,
        ReplicationMonitoringWorkflow,
    ]

    def __init__(
        self,
        host: str = "localhost",
        port: int = 7233,
        namespace: str = "default",
        task_queue: str = "migration-platform",
    ):
        self._host = host
        self._port = port
        self._namespace = namespace
        self._task_queue = task_queue
        self._client: TemporalClient | None = None
        self._worker: Worker | None = None

    async def start(self) -> None:
        """Connect to Temporal and start the worker."""
        logger.info(
            "Connecting to Temporal",
            host=self._host,
            port=self._port,
            namespace=self._namespace,
            task_queue=self._task_queue,
        )
        self._client = await TemporalClientFactory.create(
            host=self._host,
            port=self._port,
            namespace=self._namespace,
        )
        logger.info("Connected to Temporal")

        self._worker = Worker(
            client=self._client,
            task_queue=self._task_queue,
            workflows=self.WORKFLOWS,
            activities=[
                migration_activities.discover_objects,
                migration_activities.analyze_compatibility,
                migration_activities.convert_schema,
                migration_activities.generate_ddl,
                migration_activities.migrate_table,
                migration_activities.validate_table,
                migration_activities.send_notification,
                migration_activities.create_snapshot_checkpoint,
                migration_activities.save_cutover_checkpoint,
                migration_activities.rollback_cutover,
                migration_activities.commit_cutover,
                migration_activities.verify_target_snapshot,
                migration_activities.freeze_source_writes,
                migration_activities.generate_connection_switch_manifest,
            ],
            max_cached_workflows=1000,
            max_concurrent_workflow_tasks=100,
        )

        logger.info("Starting Temporal worker loop")
        await self._worker.run()

    async def stop(self) -> None:
        """Gracefully stop the worker."""
        if self._worker:
            self._worker.shutdown()
            self._worker = None

    async def start_workflow(
        self,
        workflow_type: str,
        arg: Any,
        workflow_id: str | None = None,
    ) -> str:
        """Start a workflow execution."""
        if not self._client:
            raise RuntimeError("Client not connected")

        handle = await self._client.start_workflow(
            workflow=workflow_type,
            arg=arg,
            id=workflow_id or f"{workflow_type.__name__}-{asyncio.get_running_loop().time()}",
            task_queue=self._task_queue,
        )
        return handle.id
