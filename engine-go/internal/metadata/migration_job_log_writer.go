// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package metadata

import (
	"context"
	"fmt"

	"github.com/google/uuid"
)

// AppendMigrationJobLog inserts a durable log line for the UI.
func (c *Client) AppendMigrationJobLog(
	ctx context.Context, jobID uuid.UUID, level, message string,
) error {
	_, err := c.pool.Exec(ctx, `
		INSERT INTO migration_job_logs (migration_job_id, logged_at, level, message)
		VALUES ($1, NOW(), $2, $3)`, jobID.String(), level, message)
	if err != nil {
		return fmt.Errorf("append migration job log: %w", err)
	}
	return nil
}
