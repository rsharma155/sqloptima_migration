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

// QueuedMigrationJob is a job row waiting for the Go migration-engine worker.
type QueuedMigrationJob struct {
	JobID  uuid.UUID
	Config json.RawMessage
}

// ListQueuedGoJobs returns jobs with executor=go and status=queued.
func (c *Client) ListQueuedGoJobs(ctx context.Context, limit int) ([]QueuedMigrationJob, error) {
	if limit <= 0 {
		limit = 10
	}
	rows, err := c.pool.Query(ctx, `
		SELECT migration_job_id, config
		FROM migration_jobs
		WHERE executor = 'go' AND status = 'queued'
		ORDER BY created_at ASC
		LIMIT $1`, limit)
	if err != nil {
		return nil, fmt.Errorf("list queued go jobs: %w", err)
	}
	defer rows.Close()

	var jobs []QueuedMigrationJob
	for rows.Next() {
		var idStr string
		var cfg json.RawMessage
		if err := rows.Scan(&idStr, &cfg); err != nil {
			return nil, fmt.Errorf("scan queued job: %w", err)
		}
		id, err := uuid.Parse(idStr)
		if err != nil {
			return nil, fmt.Errorf("parse job id %q: %w", idStr, err)
		}
		jobs = append(jobs, QueuedMigrationJob{JobID: id, Config: cfg})
	}
	return jobs, rows.Err()
}

// ClaimQueuedJob atomically moves a queued job to running.
func (c *Client) ClaimQueuedJob(ctx context.Context, jobID uuid.UUID) (bool, error) {
	tag, err := c.pool.Exec(ctx, `
		UPDATE migration_jobs
		SET status = 'running', started_at = NOW(), updated_at = NOW()
		WHERE migration_job_id = $1 AND status = 'queued'`, jobID.String())
	if err != nil {
		return false, fmt.Errorf("claim queued job: %w", err)
	}
	return tag.RowsAffected() > 0, nil
}

// LoadJobDispatchConfig reads migration_jobs.config for a job.
func (c *Client) LoadJobDispatchConfig(ctx context.Context, jobID uuid.UUID) (json.RawMessage, error) {
	var cfg json.RawMessage
	err := c.pool.QueryRow(ctx,
		`SELECT config FROM migration_jobs WHERE migration_job_id = $1`, jobID.String(),
	).Scan(&cfg)
	if err == pgx.ErrNoRows {
		return nil, fmt.Errorf("job not found: %s", jobID)
	}
	if err != nil {
		return nil, fmt.Errorf("load job config: %w", err)
	}
	return cfg, nil
}
