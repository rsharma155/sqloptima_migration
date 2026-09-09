// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package metadata

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// QueuedTransferJobRow is a transfer_jobs row waiting for the Go transfer worker.
type QueuedTransferJobRow struct {
	JobID  uuid.UUID
	Config json.RawMessage
}

// ListQueuedTransferJobs returns transfer_jobs with status=queued.
func (c *Client) ListQueuedTransferJobs(ctx context.Context, limit int) ([]QueuedTransferJobRow, error) {
	if limit <= 0 {
		limit = 10
	}
	rows, err := c.pool.Query(ctx, `
		SELECT transfer_job_id, config
		FROM transfer_jobs
		WHERE status = 'queued'
		ORDER BY created_at ASC
		LIMIT $1`, limit)
	if err != nil {
		return nil, fmt.Errorf("list queued transfer jobs: %w", err)
	}
	defer rows.Close()

	var jobs []QueuedTransferJobRow
	for rows.Next() {
		var idStr string
		var cfg json.RawMessage
		if err := rows.Scan(&idStr, &cfg); err != nil {
			return nil, fmt.Errorf("scan queued transfer job: %w", err)
		}
		id, err := uuid.Parse(idStr)
		if err != nil {
			return nil, fmt.Errorf("parse transfer job id %q: %w", idStr, err)
		}
		jobs = append(jobs, QueuedTransferJobRow{JobID: id, Config: cfg})
	}
	return jobs, rows.Err()
}

// ClaimQueuedTransferJob atomically moves a queued transfer job to running.
func (c *Client) ClaimQueuedTransferJob(ctx context.Context, jobID uuid.UUID) (bool, error) {
	tag, err := c.pool.Exec(ctx, `
		UPDATE transfer_jobs
		SET status = 'running', phase = 'loading', started_at = NOW(), updated_at = NOW()
		WHERE transfer_job_id = $1 AND status = 'queued'`, jobID.String())
	if err != nil {
		return false, fmt.Errorf("claim queued transfer job: %w", err)
	}
	return tag.RowsAffected() > 0, nil
}

// LoadTransferDispatchConfig reads transfer_jobs.config for a job.
func (c *Client) LoadTransferDispatchConfig(ctx context.Context, jobID uuid.UUID) (json.RawMessage, error) {
	var cfg json.RawMessage
	err := c.pool.QueryRow(ctx,
		`SELECT config FROM transfer_jobs WHERE transfer_job_id = $1`, jobID.String(),
	).Scan(&cfg)
	if err == pgx.ErrNoRows {
		return nil, fmt.Errorf("transfer job not found: %s", jobID)
	}
	if err != nil {
		return nil, fmt.Errorf("load transfer job config: %w", err)
	}
	return cfg, nil
}
