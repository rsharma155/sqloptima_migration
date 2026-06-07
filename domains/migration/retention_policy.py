"""
Module: domains/migration/retention_policy.py
Purpose: Domain value-object that captures job-retention rules.  Pure logic
         — no I/O.  The application service owns scheduling and deletion.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum


class RetentionAction(StrEnum):
    """What to do with a job that has exceeded the retention window."""

    DELETE = "delete"     # Hard-delete the job record and all child rows
    ARCHIVE = "archive"   # Mark job as archived (soft-delete); keep for audit


@dataclass(frozen=True)
class RetentionPolicy:
    """Immutable retention rule applied to migration jobs.

    Attributes:
        max_age_days: Remove/archive jobs older than this many days.
        keep_failed: If True, failed jobs are exempt from retention.
        keep_running: Always True — running jobs are never removed.
        action: What to do when a job exceeds *max_age_days*.
        max_completed_jobs: If set, keep only the N most-recent completed
            jobs regardless of age (useful for development environments).

    Example::

        policy = RetentionPolicy(max_age_days=30, keep_failed=True)
        is_eligible = policy.is_eligible_for_cleanup(status="COMPLETED", age_days=35)
        # → True
    """

    max_age_days: int = 90
    keep_failed: bool = False
    keep_running: bool = True   # always exempt running jobs
    action: RetentionAction = RetentionAction.DELETE
    max_completed_jobs: int | None = None

    # ------------------------------------------------------------------
    # Domain logic
    # ------------------------------------------------------------------

    def is_eligible_for_cleanup(self, status: str, age_days: float) -> bool:
        """Return True if a job with *status* and *age_days* should be cleaned up."""
        upper = status.upper()

        # Running jobs are always exempt
        if self.keep_running and upper in ("RUNNING", "IN_PROGRESS", "PAUSED"):
            return False

        # Optionally exempt failed jobs
        if self.keep_failed and upper in ("FAILED", "STOPPED"):
            return False

        return age_days >= self.max_age_days

    @property
    def retention_window(self) -> timedelta:
        return timedelta(days=self.max_age_days)

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def default(cls) -> "RetentionPolicy":
        """90-day retention; delete completed and failed jobs."""
        return cls()

    @classmethod
    def aggressive(cls) -> "RetentionPolicy":
        """7-day retention; keep failed for 30 days; delete completed."""
        return cls(max_age_days=7, keep_failed=False)

    @classmethod
    def conservative(cls) -> "RetentionPolicy":
        """365-day retention; keep failed indefinitely."""
        return cls(max_age_days=365, keep_failed=True)
