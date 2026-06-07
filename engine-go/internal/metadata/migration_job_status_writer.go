// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package metadata

import (
	"context"
	"fmt"

	"github.com/google/uuid"
)

// SetMigrationJobStatus updates migration_jobs.status (lowercase Python values).
func (c *Client) SetMigrationJobStatus(ctx context.Context, jobID uuid.UUID, status string) error {
	_, err := c.pool.Exec(ctx, `
		UPDATE migration_jobs
		SET status = $1, updated_at = NOW(),
		    completed_at = CASE WHEN $1 IN ('completed', 'failed', 'stopped') THEN NOW() ELSE completed_at END
		WHERE migration_job_id = $2`, status, jobID.String())
	if err != nil {
		return fmt.Errorf("set job status: %w", err)
	}
	return nil
}

// SetMigrationJobError records a failure reason on migration_jobs.error.
func (c *Client) SetMigrationJobError(ctx context.Context, jobID uuid.UUID, message string) error {
	_, err := c.pool.Exec(ctx, `
		UPDATE migration_jobs
		SET error = $1, updated_at = NOW()
		WHERE migration_job_id = $2`, message, jobID.String())
	if err != nil {
		return fmt.Errorf("set job error: %w", err)
	}
	return nil
}

// UpdateTablePlanProgress updates per-table counters in migration_table_plans.
func (c *Client) UpdateTablePlanProgress(
	ctx context.Context, jobID uuid.UUID, tableName, status string, rowsMigrated int64,
) error {
	_, err := c.pool.Exec(ctx, `
		UPDATE migration_table_plans
		SET status = $1, rows_migrated = $2
		WHERE migration_job_id = $3 AND table_name = $4`,
		status, rowsMigrated, jobID.String(), tableName)
	if err != nil {
		return fmt.Errorf("update table plan progress: %w", err)
	}
	return nil
}
