// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package transfer

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
)

// ErrTransferJobStopped is returned when the control plane issues STOP/CANCEL.
var ErrTransferJobStopped = errors.New("transfer job stopped by user")

// TransferJobCommandController enforces pause/resume/stop from transfer_commands.
type TransferJobCommandController struct {
	meta         TransferMetadataPort
	jobID        uuid.UUID
	pollInterval time.Duration
	wakeCh       <-chan struct{}
}

func NewTransferJobCommandController(
	meta TransferMetadataPort,
	jobID uuid.UUID,
	wakeCh <-chan struct{},
) *TransferJobCommandController {
	return &TransferJobCommandController{
		meta:         meta,
		jobID:        jobID,
		pollInterval: 500 * time.Millisecond,
		wakeCh:       wakeCh,
	}
}

func (c *TransferJobCommandController) CheckBeforeChunk(ctx context.Context) error {
	for {
		cmd, pending, err := c.meta.GetTransferCommand(ctx, c.jobID)
		if err != nil {
			return fmt.Errorf("poll transfer command: %w", err)
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
			_ = c.meta.AckTransferCommand(ctx, c.jobID)
			return nil
		default:
			_ = c.meta.AckTransferCommand(ctx, c.jobID)
			return nil
		}
	}
}

func (c *TransferJobCommandController) handleStop(ctx context.Context) error {
	_ = c.meta.AckTransferCommand(ctx, c.jobID)
	_ = c.meta.SetTransferJobStatus(ctx, c.jobID, "stopped")
	_ = c.meta.AppendTransferJobLog(ctx, c.jobID, "warning", "Transfer stopped by user")
	return ErrTransferJobStopped
}

func (c *TransferJobCommandController) handlePause(ctx context.Context) error {
	_ = c.meta.AckTransferCommand(ctx, c.jobID)
	_ = c.meta.SetTransferJobStatus(ctx, c.jobID, "paused")
	_ = c.meta.AppendTransferJobLog(ctx, c.jobID, "info", "Transfer paused — waiting for resume")
	return c.waitWhilePaused(ctx)
}

func (c *TransferJobCommandController) handleResume(ctx context.Context) error {
	_ = c.meta.AckTransferCommand(ctx, c.jobID)
	_ = c.meta.SetTransferJobStatus(ctx, c.jobID, "running")
	_ = c.meta.AppendTransferJobLog(ctx, c.jobID, "info", "Transfer resumed")
	return nil
}

func (c *TransferJobCommandController) waitWhilePaused(ctx context.Context) error {
	ticker := time.NewTicker(c.pollInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-c.wakeCh:
		case <-ticker.C:
		}
		cmd, pending, err := c.meta.GetTransferCommand(ctx, c.jobID)
		if err != nil {
			return fmt.Errorf("poll transfer command while paused: %w", err)
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
			_ = c.meta.AckTransferCommand(ctx, c.jobID)
		default:
			_ = c.meta.AckTransferCommand(ctx, c.jobID)
		}
	}
}
