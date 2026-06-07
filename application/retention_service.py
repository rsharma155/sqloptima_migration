"""
Module: application/retention_service.py
Purpose: Applies the RetentionPolicy to persisted migration jobs.
         Deletes (or archives) jobs that have exceeded the configured age.
         Designed to be called from a scheduled background task or an
         admin-triggered API endpoint.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.migration.retention_policy import RetentionAction, RetentionPolicy
from infrastructure.metadata_db.models import MigrationJobRecord
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


@dataclass
class RetentionResult:
    """Summary of a single retention run."""

    policy_max_age_days: int
    scanned: int = 0
    deleted: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    ran_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


class RetentionService:
    """Applies a :class:`RetentionPolicy` to the jobs in the metadata DB.

    All deletions are committed by the caller — the service only flushes
    within the session it receives.  Pass ``dry_run=True`` to preview
    which jobs would be deleted without actually removing them.

    Example::

        svc = RetentionService(session, RetentionPolicy.default())
        result = await svc.run(dry_run=False)
        print(f"Deleted {result.deleted} jobs")
    """

    def __init__(
        self,
        session: AsyncSession,
        policy: RetentionPolicy | None = None,
    ) -> None:
        self._session = session
        self._policy = policy or RetentionPolicy.default()

    async def run(self, dry_run: bool = False) -> RetentionResult:
        """Scan all jobs and apply the retention policy.

        Args:
            dry_run: If True, log what *would* be deleted but make no changes.

        Returns:
            :class:`RetentionResult` with counts of scanned / deleted / skipped.
        """
        result = RetentionResult(policy_max_age_days=self._policy.max_age_days)
        now = datetime.now(UTC)

        rows = await self._session.execute(
            select(MigrationJobRecord).order_by(MigrationJobRecord.created_at)
        )
        jobs = list(rows.scalars().all())
        result.scanned = len(jobs)

        eligible_ids: list[str] = []

        for job in jobs:
            created = job.created_at
            if created is None:
                result.skipped += 1
                continue

            # Ensure timezone-aware comparison
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            age_days = (now - created).total_seconds() / 86_400

            if self._policy.is_eligible_for_cleanup(job.status, age_days):
                eligible_ids.append(job.migration_job_id)
                logger.info(
                    "retention_eligible",
                    job_id=job.migration_job_id,
                    status=job.status,
                    age_days=round(age_days, 1),
                    dry_run=dry_run,
                )
            else:
                result.skipped += 1

        if dry_run:
            result.deleted = len(eligible_ids)
            logger.info(
                "retention_dry_run",
                would_delete=result.deleted,
                scanned=result.scanned,
            )
            return result

        # Check max_completed_jobs limit
        if self._policy.max_completed_jobs is not None:
            eligible_ids = await self._apply_max_jobs_limit(
                eligible_ids, self._policy.max_completed_jobs
            )

        # Execute deletion
        if eligible_ids and self._policy.action == RetentionAction.DELETE:
            await self._session.execute(
                delete(MigrationJobRecord).where(
                    MigrationJobRecord.migration_job_id.in_(eligible_ids)
                )
            )
            await self._session.flush()
            result.deleted = len(eligible_ids)

        logger.info(
            "retention_complete",
            scanned=result.scanned,
            deleted=result.deleted,
            skipped=result.skipped,
        )
        return result

    async def _apply_max_jobs_limit(
        self, candidate_ids: list[str], max_jobs: int
    ) -> list[str]:
        """Keep the *max_jobs* most-recent completed jobs; include the rest in candidates."""
        rows = await self._session.execute(
            select(MigrationJobRecord.migration_job_id, MigrationJobRecord.completed_at)
            .where(MigrationJobRecord.status == "COMPLETED")
            .order_by(MigrationJobRecord.completed_at.desc())
            .limit(max_jobs)
        )
        protect_ids = {row[0] for row in rows}
        return [jid for jid in candidate_ids if jid not in protect_ids]
