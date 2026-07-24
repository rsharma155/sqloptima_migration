"""
Module: orchestration/workflows.py
Purpose: Temporal.io workflow definitions for migration orchestration
Author: Migration Platform Team
Created: 2026-05-22
Domain: Orchestration
Dependencies: temporalio
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from temporalio import workflow
from temporalio.common import RetryPolicy

# ── Activity Interfaces ──────────────────────────────────────────────

class MigrationActivity:
    """Activities invoked by Temporal workflows."""

    @staticmethod
    async def discover_objects(connection_id: str, schema: str) -> list[dict]:
        raise NotImplementedError

    @staticmethod
    async def analyze_compatibility(objects: list[dict]) -> list[dict]:
        raise NotImplementedError

    @staticmethod
    async def convert_schema(object_id: str, sql: str) -> dict:
        raise NotImplementedError

    @staticmethod
    async def generate_ddl(object_id: str, ir: dict) -> str:
        raise NotImplementedError

    @staticmethod
    async def migrate_table(
        schema: str,
        table: str,
        columns: list[str],
        chunk_size: int,
        parallel_workers: int,
    ) -> dict:
        raise NotImplementedError

    @staticmethod
    async def validate_table(
        source_conn: str,
        target_conn: str,
        schema: str,
        table: str,
    ) -> dict:
        raise NotImplementedError

    @staticmethod
    async def send_notification(channel: str, message: str) -> None:
        raise NotImplementedError

    @staticmethod
    async def create_snapshot_checkpoint(job_id: str, table: str, lsn: str) -> dict:
        raise NotImplementedError

    @staticmethod
    async def save_cutover_checkpoint(
        job_id: str,
        tables: list[str],
        lsn: str,
        schema: str,
        target_schema: str,
        snapshot_ref: str | None,
    ) -> dict:
        raise NotImplementedError

    @staticmethod
    async def rollback_cutover(job_id: str, target_connection_id: str) -> dict:
        raise NotImplementedError

    @staticmethod
    async def verify_target_snapshot(
        target_connection_id: str,
        tables: list[str],
        snapshot_ref: str | None,
        target_schema: str,
    ) -> dict:
        raise NotImplementedError

    @staticmethod
    async def freeze_source_writes(
        source_connection_id: str,
        schema: str,
        tables: list[str],
        job_id: str,
    ) -> dict:
        raise NotImplementedError

    @staticmethod
    async def generate_connection_switch_manifest(
        job_id: str,
        source_connection_id: str,
        target_connection_id: str,
        tables: list[str],
        target_schema: str,
    ) -> dict:
        raise NotImplementedError

    @staticmethod
    async def commit_cutover(
        job_id: str,
        source_connection_id: str,
        target_connection_id: str,
        tables: list[str],
        target_schema: str,
    ) -> dict:
        raise NotImplementedError


# ── Workflow Definitions ─────────────────────────────────────────────

@dataclass
class MigrationWorkflowInput:
    """Input for the full migration workflow."""

    job_id: UUID = field(default_factory=uuid4)
    source_connection_id: str = ""
    target_connection_id: str = ""
    schemas: list[str] = field(default_factory=lambda: ["dbo"])
    tables: list[str] = field(default_factory=list)
    chunk_size: int = 10000
    parallel_workers: int = 4
    validate_after_migration: bool = True
    notify_on_completion: bool = True
    notification_channels: list[str] = field(default_factory=lambda: ["console"])


@dataclass
class WorkflowResult:
    """Result of a workflow execution."""

    job_id: UUID
    success: bool = False
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    total_duration_seconds: float = 0.0
    objects_discovered: int = 0
    objects_converted: int = 0
    tables_migrated: int = 0
    tables_validated: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class PeriodicValidationWorkflowInput:
    """Input for the periodic validation workflow."""

    source_connection_id: str
    target_connection_id: str
    tables: list[str] = field(default_factory=list)
    interval_minutes: int = 60
    schema: str = "public"


@dataclass
class CutoverWorkflowInput:
    """Input for the near-zero-downtime cutover workflow."""

    job_id: UUID = field(default_factory=uuid4)
    source_connection_id: str = ""
    target_connection_id: str = ""
    tables: list[str] = field(default_factory=list)
    schema: str = "dbo"
    target_schema: str = "public"
    require_human_approval: bool = True
    rollback_on_failure: bool = True
    validation_threshold_pct: float = 100.0
    snapshot_ref: str | None = None
    rollback_window_minutes: int = 60


# ── Workflow Implementations ─────────────────────────────────────────

def _workflow_now() -> datetime:
    """Return workflow-safe time, falling back for direct unit-test invocation."""
    try:
        return workflow.now()
    except Exception:
        return datetime.now(UTC)


@workflow.defn
class FullMigrationWorkflow:
    """Orchestrates the entire migration: discover → convert → migrate → validate."""

    def __init__(self) -> None:
        # Do not call uuid4()/datetime.now() here — Temporal sandbox forbids
        # non-deterministic APIs during workflow construction.
        self._result: WorkflowResult | None = None

    @workflow.run
    async def run(self, inp: MigrationWorkflowInput) -> WorkflowResult:
        self._result = WorkflowResult(
            job_id=inp.job_id,
            started_at=_workflow_now(),
        )
        result = self._result

        try:
            # Step 1: Discover objects
            workflow.logger.info("Starting discovery phase")
            all_objects = []
            for schema in inp.schemas:
                objects = await workflow.execute_activity(
                    "discover_objects",
                    args=[inp.source_connection_id, schema],
                    start_to_close_timeout=timedelta(minutes=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                all_objects.extend(objects)
            result.objects_discovered = len(all_objects)
            workflow.logger.info(f"Discovered {len(all_objects)} objects")

            # Step 2: Analyze compatibility
            workflow.logger.info("Analyzing compatibility")
            await workflow.execute_activity(
                "analyze_compatibility",
                args=[all_objects],
                start_to_close_timeout=timedelta(minutes=10),
            )

            # Step 3: Convert schema objects
            workflow.logger.info("Starting schema conversion")
            converted_count = 0
            for obj in all_objects:
                if obj.get("object_type") in ("TABLE", "VIEW", "PROCEDURE", "FUNCTION"):
                    await workflow.execute_activity(
                        "convert_schema",
                        args=[obj.get("object_id", ""), obj.get("source_definition", "")],
                        start_to_close_timeout=timedelta(minutes=5),
                        retry_policy=RetryPolicy(maximum_attempts=2),
                    )
                    converted_count += 1
            result.objects_converted = converted_count

            # Step 4: Migrate tables
            workflow.logger.info("Starting data migration")
            table_list = inp.tables or [
                o["name"] for o in all_objects if o.get("object_type") == "TABLE"
            ]
            migrated_count = 0
            for table in table_list:
                mig = await workflow.execute_activity(
                    "migrate_table",
                    args=["dbo", table, ["*"], inp.chunk_size, inp.parallel_workers],
                    start_to_close_timeout=timedelta(hours=4),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
                if mig.get("status") == "completed":
                    migrated_count += 1
                else:
                    result.errors.append(f"Migration failed for {table}: {mig.get('error')}")
            result.tables_migrated = migrated_count

            # Step 5: Validate
            validated_count = 0
            if inp.validate_after_migration:
                workflow.logger.info("Starting validation")
                for table in table_list:
                    val = await workflow.execute_activity(
                        "validate_table",
                        args=[
                            inp.source_connection_id,
                            inp.target_connection_id,
                            "dbo",
                            table,
                        ],
                        start_to_close_timeout=timedelta(minutes=30),
                    )
                    if val.get("status") == "passed":
                        validated_count += 1
                result.tables_validated = validated_count

            # Step 6: Notify
            if inp.notify_on_completion:
                for channel in inp.notification_channels:
                    await workflow.execute_activity(
                        "send_notification",
                        args=[
                            channel,
                            f"Migration job {inp.job_id} completed: "
                            f"{migrated_count} tables migrated, {validated_count} validated",
                        ],
                        start_to_close_timeout=timedelta(seconds=30),
                    )

            result.success = True
            result.completed_at = _workflow_now()
            duration = (result.completed_at - result.started_at).total_seconds()
            result.total_duration_seconds = duration

        except Exception as e:
            workflow.logger.error(f"Workflow failed: {e}")
            result.success = False
            result.errors.append(str(e))
            result.completed_at = _workflow_now()

        return result


@workflow.defn
class CutoverWorkflow:
    """Manages near-zero-downtime cutover with human approval gate."""

    def __init__(self) -> None:
        self._approved: bool = False
        self._signal_received: bool = False

    @workflow.signal
    def approve_cutover(self) -> None:
        self._approved = True
        self._signal_received = True

    @workflow.signal
    def reject_cutover(self, reason: str = "") -> None:
        self._approved = False
        self._signal_received = True

    @workflow.query
    def is_approved(self) -> bool:
        return self._approved

    @workflow.run
    async def run(self, inp: CutoverWorkflowInput) -> WorkflowResult:
        result = WorkflowResult(job_id=inp.job_id)

        try:
            # Phase 0: Verify target snapshot (§13.3)
            snap = await workflow.execute_activity(
                MigrationActivity.verify_target_snapshot,
                inp.target_connection_id,
                inp.tables,
                inp.snapshot_ref,
                inp.target_schema,
                start_to_close_timeout=timedelta(minutes=30),
            )
            if not snap.get("verified"):
                result.success = False
                result.errors.append(snap.get("message", "Target snapshot verification failed"))
                result.completed_at = datetime.now(UTC)
                return result

            # Phase 0b: Write-freeze baseline on source
            await workflow.execute_activity(
                MigrationActivity.freeze_source_writes,
                inp.source_connection_id,
                inp.schema,
                inp.tables,
                str(inp.job_id),
                start_to_close_timeout=timedelta(minutes=10),
            )

            # Phase 1: Final sync
            workflow.logger.info("Starting final sync phase")
            for table in inp.tables:
                await workflow.execute_activity(
                    MigrationActivity.migrate_table,
                    "dbo",
                    table,
                    ["*"],
                    5000,
                    4,
                    start_to_close_timeout=timedelta(hours=1),
                )

            # Phase 2: Create durable rollback checkpoint (all tables)
            await workflow.execute_activity(
                MigrationActivity.save_cutover_checkpoint,
                str(inp.job_id),
                inp.tables,
                "FINAL",
                inp.schema,
                inp.target_schema,
                inp.snapshot_ref,
                start_to_close_timeout=timedelta(seconds=30),
            )

            # Phase 3: Wait for human approval
            if inp.require_human_approval:
                workflow.logger.info("Waiting for human approval signal")
                for _ in range(60):  # wait up to 30 min
                    await workflow.sleep(timedelta(seconds=30))
                    if self._signal_received:
                        break

                if not self._signal_received:
                    return self._timeout_result(result)

                if not self._approved:
                    workflow.logger.info("Cutover rejected by user")
                    result.success = False
                    result.errors.append("Cutover rejected by human operator")
                    result.completed_at = datetime.now(UTC)
                    return result

            # Phase 4: Validate
            workflow.logger.info("Validating final state")
            validated = 0
            for table in inp.tables:
                vr = await workflow.execute_activity(
                    MigrationActivity.validate_table,
                    inp.source_connection_id,
                    inp.target_connection_id,
                    "dbo",
                    table,
                    start_to_close_timeout=timedelta(minutes=30),
                )
                if vr.get("status") == "passed":
                    validated += 1

            validation_pct = (validated / len(inp.tables) * 100) if inp.tables else 100
            if validation_pct < inp.validation_threshold_pct:
                if inp.rollback_on_failure:
                    workflow.logger.error("Validation below threshold, initiating rollback")
                    rb = await workflow.execute_activity(
                        MigrationActivity.rollback_cutover,
                        str(inp.job_id),
                        inp.target_connection_id,
                        start_to_close_timeout=timedelta(minutes=15),
                    )
                    result.success = False
                    result.errors.append(
                        f"Validation failed: {validation_pct}% < {inp.validation_threshold_pct}% threshold"
                    )
                    if rb.get("errors"):
                        result.errors.extend(rb["errors"])
                else:
                    result.success = True
                    workflow.logger.warning(f"Proceeding despite {validation_pct}% validation")
            else:
                commit_result = await workflow.execute_activity(
                    MigrationActivity.commit_cutover,
                    str(inp.job_id),
                    inp.source_connection_id,
                    inp.target_connection_id,
                    inp.tables,
                    inp.target_schema,
                    start_to_close_timeout=timedelta(seconds=30),
                )
                if not commit_result.get("success", True):
                    result.errors.append(commit_result.get("error", "commit failed"))

            if not result.errors:
                result.success = True
            result.tables_migrated = len(inp.tables)
            result.tables_validated = validated
            result.completed_at = datetime.now(UTC)

        except Exception as e:
            workflow.logger.error(f"Cutover workflow failed: {e}")
            result.success = False
            result.errors.append(str(e))
            result.completed_at = datetime.now(UTC)

        return result

    def _timeout_result(self, result: WorkflowResult) -> WorkflowResult:
        result.success = False
        result.errors.append("Cutover timed out waiting for human approval")
        result.completed_at = datetime.now(UTC)
        return result


@workflow.defn
class PeriodicValidationWorkflow:
    """Runs periodic validation on migrated tables."""

    @workflow.run
    async def run(self, inp: PeriodicValidationWorkflowInput) -> None:
        while True:
            for table in inp.tables:
                await workflow.execute_activity(
                    MigrationActivity.validate_table,
                    inp.source_connection_id,
                    inp.target_connection_id,
                    inp.schema,
                    table,
                    start_to_close_timeout=timedelta(minutes=30),
                )
            await workflow.sleep(timedelta(minutes=inp.interval_minutes))


@workflow.defn
class ReplicationMonitoringWorkflow:
    """Monitors replication lag and alerts on threshold breach."""

    @workflow.run
    async def run(
        self,
        tables: list[str],
        lag_threshold_seconds: int = 30,
        check_interval_seconds: int = 15,
    ) -> None:
        while True:
            for table in tables:
                lag = await workflow.execute_activity(
                    "check_replication_lag",
                    table,
                    start_to_close_timeout=timedelta(seconds=30),
                )
                if isinstance(lag, (int, float)) and lag > lag_threshold_seconds:
                    await workflow.execute_activity(
                        MigrationActivity.send_notification,
                        "alert",
                        f"Replication lag {lag}s for {table} (threshold {lag_threshold_seconds}s)",
                        start_to_close_timeout=timedelta(seconds=15),
                    )
            await workflow.sleep(timedelta(seconds=check_interval_seconds))
