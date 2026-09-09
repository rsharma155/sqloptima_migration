// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package transfer

import (
	"context"
	"errors"
	"fmt"

	"github.com/google/uuid"
	"github.com/ravisharma/sql-optima/engine-go/internal/metadata"
)

// TransferConstraintApplier applies the operator-accepted destination plan only.
type TransferConstraintApplier interface {
	Apply(ctx context.Context, target *metadata.ProjectConnection, items []TransferConstraintItem) error
	Restore(ctx context.Context, target *metadata.ProjectConnection, items []TransferConstraintItem) error
}

// TransferGoJobHandler runs extract→load for a claimed transfer job.
type TransferGoJobHandler struct {
	meta          TransferMetadataPort
	mover         TransferTableMover
	applier       TransferConstraintApplier
	commandPoller *metadata.CommandPoller
	metadataURL   string
}

func NewTransferGoJobHandler(
	meta TransferMetadataPort,
	mover TransferTableMover,
	commandPoller *metadata.CommandPoller,
) *TransferGoJobHandler {
	return &TransferGoJobHandler{meta: meta, mover: mover, commandPoller: commandPoller}
}

func (h *TransferGoJobHandler) WithMetadataURL(url string) *TransferGoJobHandler {
	h.metadataURL = url
	return h
}

func (h *TransferGoJobHandler) WithConstraintApplier(applier TransferConstraintApplier) *TransferGoJobHandler {
	h.applier = applier
	return h
}

func (h *TransferGoJobHandler) Run(ctx context.Context, job *QueuedTransferJob) error {
	cfg, err := ParseTransferDispatchConfig(job.Config)
	if err != nil {
		h.failJob(ctx, job.JobID, err.Error())
		return err
	}
	if !PathSupportsDataPlane(cfg.Path) {
		msg := fmt.Sprintf("transfer path %s is not implemented in the data plane yet", cfg.Path)
		h.failJob(ctx, job.JobID, msg)
		return fmt.Errorf("%s", msg)
	}

	jobID, _ := uuid.Parse(cfg.JobID)
	runCtx, cancel := context.WithCancel(ctx)
	defer cancel()

	wakeCh := make(chan struct{}, 1)
	if h.commandPoller != nil && h.metadataURL != "" {
		go func() {
			_ = h.commandPoller.ListenLoopOn(runCtx, h.metadataURL, "transfer_commands", func() {
				select {
				case wakeCh <- struct{}{}:
				default:
				}
			})
		}()
	}
	commandCtrl := NewTransferJobCommandController(h.meta, jobID, wakeCh)
	if live, ok := h.mover.(*LiveTransferTableMover); ok {
		live.ConfigureTransferJob(cfg, h.meta)
		live.beforeChunk = commandCtrl.CheckBeforeChunk
	}
	if err := commandCtrl.CheckBeforeChunk(runCtx); err != nil {
		if errors.Is(err, ErrTransferJobStopped) {
			return nil
		}
		h.failJob(runCtx, jobID, err.Error())
		return err
	}

	srcID, err := uuid.Parse(cfg.Source.ConnectionID)
	if err != nil {
		h.failJob(runCtx, jobID, "invalid source connection id")
		return err
	}
	tgtID, err := uuid.Parse(cfg.Target.ConnectionID)
	if err != nil {
		h.failJob(runCtx, jobID, "invalid target connection id")
		return err
	}
	srcConn, err := h.meta.LoadProjectConnection(runCtx, srcID)
	if err != nil {
		h.failJob(runCtx, jobID, fmt.Sprintf("load source connection: %v", err))
		return err
	}
	tgtConn, err := h.meta.LoadProjectConnection(runCtx, tgtID)
	if err != nil {
		h.failJob(runCtx, jobID, fmt.Sprintf("load target connection: %v", err))
		return err
	}

	plan, err := ParseTransferConstraintPlan(cfg.ConstraintPlan)
	if err != nil {
		h.failJob(runCtx, jobID, err.Error())
		return err
	}
	disabled := DisableConstraintItems(plan)
	if len(disabled) > 0 && !plan.OperatorReviewed {
		msg := "destination constraint disable requires operator review"
		h.failJob(runCtx, jobID, msg)
		return fmt.Errorf("%s", msg)
	}

	applied := false
	restoreNow := true
	defer func() {
		if !applied || h.applier == nil || !restoreNow {
			return
		}
		_ = h.meta.AppendTransferJobLog(context.Background(), jobID, "info",
			fmt.Sprintf("Restoring %d destination constraint(s)", len(disabled)))
		if err := h.applier.Restore(context.Background(), tgtConn, disabled); err != nil {
			_ = h.meta.AppendTransferJobLog(context.Background(), jobID, "error",
				fmt.Sprintf("Constraint restore failed: %v", err))
		}
	}()

	if len(disabled) > 0 {
		if h.applier == nil {
			msg := "constraint applier is not configured"
			h.failJob(runCtx, jobID, msg)
			return fmt.Errorf("%s", msg)
		}
		_ = h.meta.SetTransferJobStatus(runCtx, jobID, "preparing")
		_ = h.meta.AppendTransferJobLog(runCtx, jobID, "info",
			fmt.Sprintf("Applying %d operator-approved destination disable(s)", len(disabled)))
		applied = true
		if err := h.applier.Apply(runCtx, tgtConn, disabled); err != nil {
			h.failJob(runCtx, jobID, err.Error())
			return err
		}
		applied = true
	}

	_ = h.meta.SetTransferJobStatus(runCtx, jobID, "running")
	_ = h.meta.AppendTransferJobLog(runCtx, jobID, "info",
		fmt.Sprintf("Transfer worker claimed job — %s, %d table(s)", cfg.Path, len(cfg.Tables)))

	var totalRows int64
	tablesDone := 0
	for _, table := range cfg.Tables {
		if err := commandCtrl.CheckBeforeChunk(runCtx); err != nil {
			if errors.Is(err, ErrTransferJobStopped) {
				restoreNow = plan == nil || plan.OnStop != "leave_disabled"
				return nil
			}
			h.failJob(runCtx, jobID, err.Error())
			return err
		}
		tableKey := table.SourceSchema + "." + table.SourceTable
		_ = h.meta.UpdateTransferTableProgress(runCtx, jobID, table.SourceTable, "running", 0)
		_ = h.meta.AppendTransferTableLog(runCtx, jobID, tableKey, "info",
			fmt.Sprintf("Transferring %s.%s → %s.%s",
				table.SourceSchema, table.SourceTable, table.TargetSchema, table.TargetTable))
		rows, err := h.mover.Move(runCtx, jobID, srcConn, tgtConn, table)
		if err != nil {
			if errors.Is(err, ErrTransferJobStopped) {
				restoreNow = plan == nil || plan.OnStop != "leave_disabled"
				return nil
			}
			restoreNow = plan == nil || plan.OnStop != "leave_disabled"
			_ = h.meta.SetTransferTableError(runCtx, jobID, table.SourceSchema, table.SourceTable, err.Error())
			_ = h.meta.AppendTransferTableLog(runCtx, jobID, tableKey, "error", err.Error())
			h.failJob(runCtx, jobID, err.Error())
			return err
		}
		totalRows += rows
		tablesDone++
		_ = h.meta.UpdateTransferTableProgress(runCtx, jobID, table.SourceTable, "completed", rows)
		_ = h.meta.UpdateTransferJobTotals(runCtx, jobID, totalRows, tablesDone)
		_ = h.meta.AppendTransferTableLog(runCtx, jobID, tableKey, "success",
			fmt.Sprintf("Copied %d row(s) for %s", rows, tableKey))
	}
	_ = h.meta.UpdateTransferJobTotals(runCtx, jobID, totalRows, tablesDone)
	_ = h.meta.AppendTransferJobLog(runCtx, jobID, "success",
		fmt.Sprintf("Transfer completed — %d row(s) across %d table(s)", totalRows, tablesDone))
	_ = h.meta.SetTransferJobStatus(runCtx, jobID, "completed")
	return nil
}

func (h *TransferGoJobHandler) failJob(ctx context.Context, jobID uuid.UUID, message string) {
	_ = h.meta.SetTransferJobError(ctx, jobID, message)
	_ = h.meta.AppendTransferJobLog(ctx, jobID, "error", message)
	_ = h.meta.SetTransferJobStatus(ctx, jobID, "failed")
}
