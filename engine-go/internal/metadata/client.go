// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package metadata

import (
	"context"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/ravisharma/sql-optima/engine-go/internal/core"
)

// Client provides read/write access to the shared PostgreSQL metadata repository.
// The metadata DB is written by the Python control-plane API and read by the Go
// data-plane engine. All queries use parameterised statements.
type Client struct {
	pool *pgxpool.Pool
}

// Connect creates a connection pool to the metadata DB.
func Connect(ctx context.Context, databaseURL string) (*Client, error) {
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		return nil, fmt.Errorf("metadata connect: %w", err)
	}
	return &Client{pool: pool}, nil
}

// Close releases the connection pool.
func (c *Client) Close() { c.pool.Close() }

// ---------------------------------------------------------------------------
// Command queries
// ---------------------------------------------------------------------------

// GetCommand reads an unacknowledged command for a job from the metadata DB.
// Returns ("", false, nil) when no pending command exists.
func (c *Client) GetCommand(ctx context.Context, jobID uuid.UUID) (core.Command, bool, error) {
	var cmdStr string
	err := c.pool.QueryRow(ctx,
		`SELECT command FROM migration_commands
		 WHERE migration_job_id = $1 AND acked_at IS NULL`,
		jobID.String(),
	).Scan(&cmdStr)
	if err != nil {
		return "", false, nil
	}
	cmd, err := core.ParseCommand(cmdStr)
	if err != nil {
		return "", false, fmt.Errorf("parse command %q: %w", cmdStr, err)
	}
	return cmd, true, nil
}

// AckCommand marks the command as acknowledged by setting acked_at = NOW().
func (c *Client) AckCommand(ctx context.Context, jobID uuid.UUID) error {
	_, err := c.pool.Exec(ctx,
		"UPDATE migration_commands SET acked_at = NOW() WHERE migration_job_id = $1", jobID.String())
	return err
}

// ---------------------------------------------------------------------------
// Job status queries
// ---------------------------------------------------------------------------

// UpdateJobStatus writes a new status string to migration_jobs.
func (c *Client) UpdateJobStatus(ctx context.Context, jobID uuid.UUID, status string) error {
	_, err := c.pool.Exec(ctx,
		`UPDATE migration_jobs SET status = $1, updated_at = NOW()
		 WHERE migration_job_id = $2`,
		status, jobID.String())
	return err
}

// SyncChunkProgress updates progress counters in migration_table_plans.
func (c *Client) SyncChunkProgress(
	ctx context.Context, chunkID uuid.UUID, status string, rowsMigrated int64,
) error {
	_, err := c.pool.Exec(ctx,
		"UPDATE migration_table_plans SET status = $1, rows_migrated = $2 WHERE id = $3",
		status, rowsMigrated, chunkID)
	return err
}

// UpdateJobProgress atomically updates job-level row and table counters.
func (c *Client) UpdateJobProgress(
	ctx context.Context, jobID uuid.UUID, rowsMigrated int64, tablesDone int32,
) error {
	_, err := c.pool.Exec(ctx,
		`UPDATE migration_jobs SET rows_migrated = $1, tables_done = $2, updated_at = NOW()
		 WHERE migration_job_id = $3`,
		rowsMigrated, tablesDone, jobID.String())
	return err
}
