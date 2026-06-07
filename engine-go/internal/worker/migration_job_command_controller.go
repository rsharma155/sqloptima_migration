// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
)

// ErrJobStopped is returned when the control plane issues STOP/CANCEL.
var ErrJobStopped = errors.New("migration job stopped by user")

// MigrationJobCommandController enforces pause/resume/stop commands from the
// metadata DB before each chunk operation.
type MigrationJobCommandController struct {
	meta         MigrationMetadataPort
	jobID        uuid.UUID
	pollInterval time.Duration
	wakeCh       <-chan struct{}
}

func NewMigrationJobCommandController(
	meta MigrationMetadataPort,
	jobID uuid.UUID,
	wakeCh <-chan struct{},
) *MigrationJobCommandController {
	return &MigrationJobCommandController{
		meta:         meta,
		jobID:        jobID,
		pollInterval: 500 * time.Millisecond,
		wakeCh:       wakeCh,
	}
}

// CheckBeforeChunk polls for pending commands and blocks while paused.
func (c *MigrationJobCommandController) CheckBeforeChunk(ctx context.Context) error {
	for {
		cmd, pending, err := c.meta.GetCommand(ctx, c.jobID)
		if err != nil {
			return fmt.Errorf("poll migration command: %w", err)
		}
		if !pending {
			return nil
		}

		switch {
		case cmd.IsStop():
			return c.handleStop(ctx)
		case cmd.IsPause():
			if err := c.handlePause(ctx); err != nil {
				return err
			}
			continue
		case cmd == core.CommandResume:
			return c.handleResume(ctx)
		case cmd == core.CommandStart:
			_ = c.meta.AckCommand(ctx, c.jobID)
			return nil
		default:
			_ = c.meta.AckCommand(ctx, c.jobID)
			return nil
		}
	}
}

func (c *MigrationJobCommandController) handleStop(ctx context.Context) error {
	_ = c.meta.AckCommand(ctx, c.jobID)
	_ = c.meta.SetMigrationJobStatus(ctx, c.jobID, "stopped")
	_ = c.meta.AppendMigrationJobLog(ctx, c.jobID, "warning", "Migration stopped by user")
	return ErrJobStopped
}

func (c *MigrationJobCommandController) handlePause(ctx context.Context) error {
	_ = c.meta.AckCommand(ctx, c.jobID)
	_ = c.meta.SetMigrationJobStatus(ctx, c.jobID, "paused")
	_ = c.meta.AppendMigrationJobLog(ctx, c.jobID, "info", "Migration paused — waiting for resume")
	return c.waitWhilePaused(ctx)
}

func (c *MigrationJobCommandController) handleResume(ctx context.Context) error {
	_ = c.meta.AckCommand(ctx, c.jobID)
	_ = c.meta.SetMigrationJobStatus(ctx, c.jobID, "running")
	_ = c.meta.AppendMigrationJobLog(ctx, c.jobID, "info", "Migration resumed")
	return nil
}

func (c *MigrationJobCommandController) waitWhilePaused(ctx context.Context) error {
	ticker := time.NewTicker(c.pollInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-c.wakeCh:
		case <-ticker.C:
		}

		cmd, pending, err := c.meta.GetCommand(ctx, c.jobID)
		if err != nil {
			return fmt.Errorf("poll migration command while paused: %w", err)
		}
		if !pending {
			continue
		}

		switch {
		case cmd.IsStop():
			return c.handleStop(ctx)
		case cmd == core.CommandResume:
			return c.handleResume(ctx)
		case cmd.IsPause():
			_ = c.meta.AckCommand(ctx, c.jobID)
		default:
			_ = c.meta.AckCommand(ctx, c.jobID)
		}
	}
}
