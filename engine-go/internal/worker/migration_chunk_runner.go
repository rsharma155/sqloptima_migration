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
	"github.com/ravisharma/sql-optima/engine-go/internal/extractor"
	"github.com/ravisharma/sql-optima/engine-go/internal/loader"
	"github.com/ravisharma/sql-optima/engine-go/internal/planner"
)

type chunkRunOutcome struct {
	rows  int64
	durMs int64
}

func (m *MigrationTableDataMover) newTableSizer(table GoTableDispatchPayload) *planner.AdaptiveChunkSizer {
	if m.runtime.Sizer == nil && m.runtime.ChunkCfg.MinSize == 0 {
		return nil
	}
	initial := m.chunkSize
	if table.ChunkSize > 0 {
		initial = int64(table.ChunkSize)
	} else if m.runtime.Sizer != nil {
		initial = m.runtime.Sizer.CurrentSize()
	}
	min, max, target := m.runtime.ChunkCfg.MinSize, m.runtime.ChunkCfg.MaxSize, m.runtime.ChunkCfg.TargetMs
	if min < 1 {
		min = 1_000
	}
	if max < min {
		max = min
	}
	if target < 1 {
		target = 2_000
	}
	return planner.NewAdaptiveChunkSizer(initial, min, max, target)
}

func (m *MigrationTableDataMover) planChunkSize(table GoTableDispatchPayload, tableSizer *planner.AdaptiveChunkSizer) int64 {
	if table.ChunkSize > 0 {
		return int64(table.ChunkSize)
	}
	if tableSizer != nil {
		return tableSizer.CurrentSize()
	}
	if m.runtime.Sizer != nil {
		return m.runtime.Sizer.CurrentSize()
	}
	return m.chunkSize
}

func (m *MigrationTableDataMover) executeChunk(
	ctx context.Context,
	jobID uuid.UUID,
	pipeline *MigrationChunkPipeline,
	chunk core.ChunkPlan,
	table GoTableDispatchPayload,
	schema extractor.ExtractionSchema,
	transforms *MigrationColumnTransformPipeline,
	opts tableMoveOptions,
) (chunkRunOutcome, error) {
	start := time.Now()
	var onProgress loader.RowProgressFunc
	if opts.enableIntraChunkProgress && m.meta != nil {
		onProgress = newThrottledChunkProgress(
			m.meta, jobID, table.TableName, opts.jobBase, opts.tableRowsBase,
		).callback()
	}
	rows, err := runChunkWithRetry(ctx, chunk, func() (int64, error) {
		return pipeline.Run(
			ctx, chunk, table.TargetSchema, table.TableName,
			schema, m.idempotent, opts.conflictColumns, opts.extractOpts, transforms, onProgress,
		)
	})
	return chunkRunOutcome{rows: rows, durMs: time.Since(start).Milliseconds()}, err
}

func (m *MigrationTableDataMover) handleChunkFailure(
	ctx context.Context,
	jobID uuid.UUID,
	table GoTableDispatchPayload,
	chunk core.ChunkPlan,
	tableSizer *planner.AdaptiveChunkSizer,
	err error,
) error {
	if tableSizer != nil {
		tableSizer.RampDownHard()
	}
	if m.runtime.Sizer != nil {
		m.runtime.Sizer.RampDownHard()
	}
	if m.runtime.Queue != nil {
		_, _ = m.runtime.Queue.UpdateStatus(jobID, chunk.ID, core.ChunkStatusClaimed, core.ChunkStatusFailed)
	}
	var q ErrChunkQuarantined
	if errors.As(err, &q) {
		_ = m.meta.InsertMigrationQuarantine(
			ctx, jobID, table.SourceSchema, table.TableName,
			q.Chunk.ChunkIndex, q.Chunk.PKColumn, q.Chunk.StartKey, q.Chunk.EndKey,
			q.Cause.Error(),
		)
		_ = m.meta.AppendMigrationJobLog(ctx, jobID, "error",
			fmt.Sprintf("Chunk %d for %s quarantined: %v", q.Chunk.ChunkIndex, table.TableName, q.Cause))
	}
	return err
}

func (m *MigrationTableDataMover) recordChunkSuccess(
	jobID uuid.UUID,
	table GoTableDispatchPayload,
	chunk core.ChunkPlan,
	tableSizer *planner.AdaptiveChunkSizer,
	outcome chunkRunOutcome,
) {
	if tableSizer != nil {
		tableSizer.NextSize(outcome.durMs)
	}
	if m.runtime.Sizer != nil && tableSizer != m.runtime.Sizer {
		m.runtime.Sizer.NextSize(outcome.durMs)
	}
	if m.runtime.Queue != nil {
		_, _ = m.runtime.Queue.UpdateStatus(jobID, chunk.ID, core.ChunkStatusClaimed, core.ChunkStatusLoaded)
		_ = m.runtime.Queue.SetCheckpoint(jobID, tableCheckpointKey(table.SourceSchema, table.TableName), chunk.ID)
	}
	if m.runtime.Metrics != nil {
		ctx := context.Background()
		qualified := table.SourceSchema + "." + table.TableName
		m.runtime.Metrics.RecordRowsExtracted(ctx, jobID, qualified, outcome.rows)
		m.runtime.Metrics.RecordRowsLoaded(ctx, jobID, qualified, outcome.rows)
		m.runtime.Metrics.RecordChunkDuration(ctx, jobID, "extract_load", float64(outcome.durMs)/1000.0)
	}
}

func (m *MigrationTableDataMover) claimNextTableChunk(
	jobID uuid.UUID,
	schema, table string,
) (*core.ChunkPlan, error) {
	pending, err := m.runtime.Queue.ListChunksByStatus(jobID, core.ChunkStatusPending)
	if err != nil {
		return nil, err
	}
	for _, chunk := range pending {
		if !chunkMatchesTable(chunk, schema, table) {
			continue
		}
		return m.runtime.Queue.ClaimChunk(jobID, chunk.ID, m.runtime.WorkerID)
	}
	return nil, nil
}
