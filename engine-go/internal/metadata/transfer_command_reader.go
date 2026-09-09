// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package metadata

import (
	"context"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/ravisharma/sql-optima/engine-go/internal/core"
)

// GetTransferCommand reads an unacknowledged command from transfer_commands.
func (c *Client) GetTransferCommand(ctx context.Context, jobID uuid.UUID) (core.Command, bool, error) {
	var cmdStr string
	err := c.pool.QueryRow(ctx,
		`SELECT command FROM transfer_commands
		 WHERE transfer_job_id = $1 AND acked_at IS NULL`,
		jobID.String(),
	).Scan(&cmdStr)
	if err == pgx.ErrNoRows {
		return "", false, nil
	}
	if err != nil {
		return "", false, fmt.Errorf("get transfer command: %w", err)
	}
	cmd, err := core.ParseCommand(cmdStr)
	if err != nil {
		return "", false, fmt.Errorf("parse transfer command %q: %w", cmdStr, err)
	}
	return cmd, true, nil
}

// AckTransferCommand marks the current transfer command as acknowledged.
func (c *Client) AckTransferCommand(ctx context.Context, jobID uuid.UUID) error {
	_, err := c.pool.Exec(ctx,
		"UPDATE transfer_commands SET acked_at = NOW() WHERE transfer_job_id = $1",
		jobID.String())
	if err != nil {
		return fmt.Errorf("ack transfer command: %w", err)
	}
	return nil
}
