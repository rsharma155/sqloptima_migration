// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"context"
	"errors"
	"fmt"

	"github.com/google/uuid"

	"github.com/ravisharma/sql-optima/engine-go/internal/metadata"
	"github.com/ravisharma/sql-optima/engine-go/internal/planner"
)

// MigrationGoJobHandler executes extract→load for a claimed Go migration job.
type MigrationGoJobHandler struct {
	meta          MigrationMetadataPort
	connFactory   MigrationConnectionFactory
	chunkSize     int64
	metadataURL   string
	commandPoller *metadata.CommandPoller
	runtime       MigrationEngineRuntime
}

func NewMigrationGoJobHandler(
	meta MigrationMetadataPort,
	masterKey string,
	metadataURL string,
	commandPoller *metadata.CommandPoller,
	runtime MigrationEngineRuntime,
) *MigrationGoJobHandler {
	chunkSize := runtime.ChunkCfg.InitialSize
	if chunkSize < 1 {
		chunkSize = 10_000
	}
	if runtime.Sizer == nil && runtime.ChunkCfg.MinSize > 0 {
		runtime.Sizer = planner.NewAdaptiveChunkSizer(
			chunkSize,
			runtime.ChunkCfg.MinSize,
			runtime.ChunkCfg.MaxSize,
			runtime.ChunkCfg.TargetMs,
		)
	}
	return &MigrationGoJobHandler{
		meta:          meta,
		connFactory:   MigrationConnectionFactory{MasterKey: masterKey},
		chunkSize:     chunkSize,
		metadataURL:   metadataURL,
		commandPoller: commandPoller,
		runtime:       runtime,
	}
}

// Run validates dispatch config, loads connections, and migrates each table.
func (h *MigrationGoJobHandler) Run(ctx context.Context, job *QueuedJob) error {
	cfg, err := ParseGoJobDispatchConfig(job.Config)
	if err != nil {
		_ = h.meta.SetMigrationJobError(ctx, job.JobID, err.Error())
		_ = h.meta.SetMigrationJobStatus(ctx, job.JobID, "failed")
		return err
	}

	jobID, _ := uuid.Parse(cfg.JobID)
	runCtx, cancel := context.WithCancel(ctx)
	defer cancel()

	wakeCh := make(chan struct{}, 1)
	if h.commandPoller != nil && h.metadataURL != "" {
		go func() {
			_ = h.commandPoller.ListenLoop(runCtx, h.metadataURL, func() {
				select {
				case wakeCh <- struct{}{}:
				default:
				}
			})
		}()
	}

	commandCtrl := NewMigrationJobCommandController(h.meta, jobID, wakeCh)
	tableMover := NewMigrationTableDataMoverFull(
		h.meta, h.chunkSize, commandCtrl, cfg.Idempotent, cfg.ConflictColumns, cfg.UseNoLock, h.runtime,
	)

	if err := commandCtrl.CheckBeforeChunk(runCtx); err != nil {
		if errors.Is(err, ErrJobStopped) {
			return nil
		}
		h.failJob(runCtx, jobID, err.Error())
		return err
	}

	_ = h.meta.AppendMigrationJobLog(runCtx, jobID, "info",
		fmt.Sprintf("Go worker claimed job — migrating %d table(s)", len(cfg.Tables)))
	if cfg.SnapshotRef != nil && *cfg.SnapshotRef != "" {
		_ = h.meta.AppendMigrationJobLog(runCtx, jobID, "info",
			fmt.Sprintf("Target rollback snapshot_ref: %s", *cfg.SnapshotRef))
	}

	srcConn, err := h.meta.LoadProjectConnection(runCtx, uuid.MustParse(cfg.Source.ConnectionID))
	if err != nil {
		h.failJob(runCtx, jobID, fmt.Sprintf("load source connection: %v", err))
		return err
	}
	tgtConn, err := h.meta.LoadProjectConnection(runCtx, uuid.MustParse(cfg.Target.ConnectionID))
	if err != nil {
		h.failJob(runCtx, jobID, fmt.Sprintf("load target connection: %v", err))
		return err
	}

	srcCfg, err := h.connFactory.SQLServerConfig(srcConn)
	if err != nil {
		h.failJob(runCtx, jobID, err.Error())
		return err
	}
	pgURL, err := h.connFactory.PostgresURL(tgtConn)
	if err != nil {
		h.failJob(runCtx, jobID, err.Error())
		return err
	}

	var totalRows int64
	tablesDone := 0
	tablesFailed := 0
	for _, table := range cfg.Tables {
		if err := commandCtrl.CheckBeforeChunk(runCtx); err != nil {
			if errors.Is(err, ErrJobStopped) {
				return nil
			}
			h.failJob(runCtx, jobID, err.Error())
			return err
		}

		_ = h.meta.AppendMigrationJobLog(runCtx, jobID, "info",
			fmt.Sprintf("Migrating %s.%s → %s.%s",
				table.SourceSchema, table.TableName, table.TargetSchema, table.TableName))

		if table.SkipDataLoad {
			_ = h.meta.AppendMigrationJobLog(runCtx, jobID, "info",
				fmt.Sprintf("Skipping data load for %s.%s — target table already populated (use_existing)",
					table.TargetSchema, table.TableName))
			_ = h.meta.UpdateTablePlanProgress(runCtx, jobID, table.TableName, "completed", 0)
			tablesDone++
			continue
		}

		result, err := tableMover.Move(runCtx, jobID, srcCfg, pgURL, table, JobProgressBase{
			RowsMigrated: totalRows,
			TablesDone:   tablesDone,
		}, cfg.SourceThrottle)
		if err != nil {
			if errors.Is(err, ErrJobStopped) {
				return nil
			}
			tablesFailed++
			continue
		}
		totalRows += result.RowsMigrated
		tablesDone++
	}

	_ = h.meta.UpdateMigrationJobTotals(runCtx, jobID, totalRows, tablesDone)
	totalTables := len(cfg.Tables)
	if tablesFailed == totalTables {
		msg := fmt.Sprintf("Migration failed — all %d table(s) failed", totalTables)
		h.failJob(runCtx, jobID, msg)
		return fmt.Errorf("%s", msg)
	}
	if tablesFailed > 0 {
		msg := fmt.Sprintf(
			"Migration completed with %d table failure(s) — %d/%d table(s) migrated successfully, %d total row(s)",
			tablesFailed, tablesDone, totalTables, totalRows,
		)
		if cfg.SnapshotRef != nil && *cfg.SnapshotRef != "" {
			msg += fmt.Sprintf(" (snapshot_ref=%s)", *cfg.SnapshotRef)
		}
		_ = h.meta.SetMigrationJobError(runCtx, jobID, msg)
		_ = h.meta.AppendMigrationJobLog(runCtx, jobID, "warning", msg)
		_ = h.meta.SetMigrationJobStatus(runCtx, jobID, "partial")
		return nil
	}
	completeMsg := fmt.Sprintf("Migration completed successfully — %d total row(s) across %d table(s)",
		totalRows, tablesDone)
	if cfg.SnapshotRef != nil && *cfg.SnapshotRef != "" {
		completeMsg += fmt.Sprintf(" (snapshot_ref=%s)", *cfg.SnapshotRef)
	}
	_ = h.meta.AppendMigrationJobLog(runCtx, jobID, "success", completeMsg)
	_ = h.meta.SetMigrationJobStatus(runCtx, jobID, "completed")
	return nil
}

func (h *MigrationGoJobHandler) failJob(ctx context.Context, jobID uuid.UUID, message string) {
	_ = h.meta.SetMigrationJobError(ctx, jobID, message)
	_ = h.meta.AppendMigrationJobLog(ctx, jobID, "error", message)
	_ = h.meta.SetMigrationJobStatus(ctx, jobID, "failed")
}
