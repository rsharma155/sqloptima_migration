// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package metadata

import (
	"context"
	"fmt"

	"github.com/google/uuid"
)

// AppendTransferJobLog inserts a durable log line for the Transfer UI.
func (c *Client) AppendTransferJobLog(
	ctx context.Context, jobID uuid.UUID, level, message string,
) error {
	_, err := c.pool.Exec(ctx, `
		INSERT INTO transfer_job_logs (transfer_job_id, logged_at, level, message)
		VALUES ($1, NOW(), $2, $3)`, jobID.String(), level, message)
	if err != nil {
		return fmt.Errorf("append transfer job log: %w", err)
	}
	return nil
}

// AppendTransferTableLog inserts a log line scoped to one configured table.
func (c *Client) AppendTransferTableLog(
	ctx context.Context, jobID uuid.UUID, tableName, level, message string,
) error {
	_, err := c.pool.Exec(ctx, `
		INSERT INTO transfer_job_logs (transfer_job_id, logged_at, level, table_name, message)
		VALUES ($1, NOW(), $2, $3, $4)`, jobID.String(), level, tableName, message)
	if err != nil {
		return fmt.Errorf("append transfer table log: %w", err)
	}
	return nil
}

// SetTransferJobStatus updates transfer_jobs.status (lowercase Python values).
func (c *Client) SetTransferJobStatus(ctx context.Context, jobID uuid.UUID, status string) error {
	_, err := c.pool.Exec(ctx, `
		UPDATE transfer_jobs
		SET status = $1, updated_at = NOW(),
		    completed_at = CASE WHEN $1 IN ('completed', 'partial', 'failed', 'stopped') THEN NOW() ELSE completed_at END,
		    phase = CASE WHEN $1 IN ('completed', 'partial', 'failed', 'stopped') THEN 'done' ELSE phase END
		WHERE transfer_job_id = $2`, status, jobID.String())
	if err != nil {
		return fmt.Errorf("set transfer job status: %w", err)
	}
	return nil
}

// SetTransferJobError records a failure reason on transfer_jobs.error.
func (c *Client) SetTransferJobError(ctx context.Context, jobID uuid.UUID, message string) error {
	_, err := c.pool.Exec(ctx, `
		UPDATE transfer_jobs
		SET error = $1, updated_at = NOW()
		WHERE transfer_job_id = $2`, message, jobID.String())
	if err != nil {
		return fmt.Errorf("set transfer job error: %w", err)
	}
	return nil
}

// SetTransferTableError records the last error on a transfer_table_plans row.
func (c *Client) SetTransferTableError(
	ctx context.Context, jobID uuid.UUID, sourceSchema, sourceTable, message string,
) error {
	_, err := c.pool.Exec(ctx, `
		UPDATE transfer_table_plans
		SET status = 'failed',
		    error = $1,
		    error_at = NOW(),
		    error_count = COALESCE(error_count, 0) + 1
		WHERE transfer_job_id = $2 AND source_schema = $3 AND source_table = $4`,
		message, jobID.String(), sourceSchema, sourceTable)
	if err != nil {
		return fmt.Errorf("set transfer table error: %w", err)
	}
	return nil
}

// UpdateTransferTableProgress updates per-table counters in transfer_table_plans.
func (c *Client) UpdateTransferTableProgress(
	ctx context.Context, jobID uuid.UUID, tableName, status string, rowsCopied int64,
) error {
	_, err := c.pool.Exec(ctx, `
		UPDATE transfer_table_plans
		SET status = $1, rows_copied = $2
		WHERE transfer_job_id = $3 AND source_table = $4`,
		status, rowsCopied, jobID.String(), tableName)
	if err != nil {
		return fmt.Errorf("update transfer table progress: %w", err)
	}
	return nil
}

// UpdateTransferJobTotals sets job-level row/table counters.
func (c *Client) UpdateTransferJobTotals(
	ctx context.Context, jobID uuid.UUID, rowsCopied int64, tablesDone int,
) error {
	_, err := c.pool.Exec(ctx, `
		UPDATE transfer_jobs
		SET rows_copied = $1, tables_done = $2, updated_at = NOW()
		WHERE transfer_job_id = $3`,
		rowsCopied, tablesDone, jobID.String())
	if err != nil {
		return fmt.Errorf("update transfer job totals: %w", err)
	}
	return nil
}

// LoadTransferRuntimeSettings reads live chunk size / throttle for a job.
func (c *Client) LoadTransferRuntimeSettings(
	ctx context.Context, jobID uuid.UUID,
) (chunkSize int64, maxRowsPerSec *int64, err error) {
	var max *int64
	err = c.pool.QueryRow(ctx, `
		SELECT chunk_size, max_rows_per_sec
		FROM transfer_runtime_settings
		WHERE transfer_job_id = $1`, jobID.String(),
	).Scan(&chunkSize, &max)
	if err != nil {
		return 10_000, nil, nil
	}
	return chunkSize, max, nil
}
