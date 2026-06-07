// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"context"
	"errors"
	"fmt"

	"github.com/google/uuid"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
	"github.com/ravisharma/sql-optima/engine-go/internal/extractor"
	"github.com/ravisharma/sql-optima/engine-go/internal/planner"
)

// moveSequential processes chunks one at a time (default chunked strategy).
func (m *MigrationTableDataMover) moveSequential(
	ctx context.Context,
	jobID uuid.UUID,
	src extractor.SQLServerConfig,
	pgURL string,
	table GoTableDispatchPayload,
	chunks []core.ChunkPlan,
	schema extractor.ExtractionSchema,
	transforms *MigrationColumnTransformPipeline,
	opts tableMoveOptions,
	tableSizer *planner.AdaptiveChunkSizer,
) (MoveTableResult, error) {
	result := MoveTableResult{TableName: table.TableName}
	pipeline := NewMigrationChunkPipeline(src, pgURL)

	if m.runtime.Queue != nil {
		return m.moveSequentialQueued(ctx, jobID, table, schema, transforms, opts, tableSizer, pipeline, &result)
	}

	for _, chunk := range chunks {
		if err := ctx.Err(); err != nil {
			return result, err
		}
		if m.command != nil {
			if err := m.command.CheckBeforeChunk(ctx); err != nil {
				if errors.Is(err, ErrJobStopped) {
					_ = m.meta.UpdateTablePlanProgress(ctx, jobID, table.TableName, "stopped", result.RowsMigrated)
				}
				return result, err
			}
		}
		if result.ChunksRun > 0 {
			if err := sleepBetweenSourceChunks(ctx, resolveChunkDelay(table, opts.sourceThrottle)); err != nil {
				return result, err
			}
		}
		chunkOpts := opts
		chunkOpts.tableRowsBase = result.RowsMigrated
		chunkOpts.enableIntraChunkProgress = true
		outcome, err := m.executeChunk(ctx, jobID, pipeline, chunk, table, schema, transforms, chunkOpts)
		if err != nil {
			_ = m.handleChunkFailure(ctx, jobID, table, chunk, tableSizer, err)
			_ = m.meta.UpdateTablePlanProgress(ctx, jobID, table.TableName, "failed", result.RowsMigrated)
			return result, fmt.Errorf("chunk %d for %s: %w", chunk.ChunkIndex, table.TableName, err)
		}
		m.recordChunkSuccess(jobID, table, chunk, tableSizer, outcome)
		result.RowsMigrated += outcome.rows
		result.ChunksRun++
		_ = m.meta.UpdateTablePlanProgress(ctx, jobID, table.TableName, "migrating", result.RowsMigrated)
		_ = m.meta.UpdateMigrationJobTotals(
			ctx, jobID, opts.jobBase.RowsMigrated+result.RowsMigrated, opts.jobBase.TablesDone,
		)
	}
	return result, nil
}

func (m *MigrationTableDataMover) moveSequentialQueued(
	ctx context.Context,
	jobID uuid.UUID,
	table GoTableDispatchPayload,
	schema extractor.ExtractionSchema,
	transforms *MigrationColumnTransformPipeline,
	opts tableMoveOptions,
	tableSizer *planner.AdaptiveChunkSizer,
	pipeline *MigrationChunkPipeline,
	result *MoveTableResult,
) (MoveTableResult, error) {
	for {
		if err := ctx.Err(); err != nil {
			return *result, err
		}
		if m.command != nil {
			if err := m.command.CheckBeforeChunk(ctx); err != nil {
				if errors.Is(err, ErrJobStopped) {
					_ = m.meta.UpdateTablePlanProgress(ctx, jobID, table.TableName, "stopped", result.RowsMigrated)
				}
				return *result, err
			}
		}
		chunk, err := m.claimNextTableChunk(jobID, table.SourceSchema, table.TableName)
		if err != nil {
			return *result, err
		}
		if chunk == nil {
			return *result, nil
		}
		if result.ChunksRun > 0 {
			if err := sleepBetweenSourceChunks(ctx, resolveChunkDelay(table, opts.sourceThrottle)); err != nil {
				return *result, err
			}
		}
		chunkOpts := opts
		chunkOpts.tableRowsBase = result.RowsMigrated
		chunkOpts.enableIntraChunkProgress = true
		outcome, err := m.executeChunk(ctx, jobID, pipeline, *chunk, table, schema, transforms, chunkOpts)
		if err != nil {
			_ = m.handleChunkFailure(ctx, jobID, table, *chunk, tableSizer, err)
			_ = m.meta.UpdateTablePlanProgress(ctx, jobID, table.TableName, "failed", result.RowsMigrated)
			return *result, fmt.Errorf("chunk %d for %s: %w", chunk.ChunkIndex, table.TableName, err)
		}
		m.recordChunkSuccess(jobID, table, *chunk, tableSizer, outcome)
		result.RowsMigrated += outcome.rows
		result.ChunksRun++
		_ = m.meta.UpdateTablePlanProgress(ctx, jobID, table.TableName, "migrating", result.RowsMigrated)
		_ = m.meta.UpdateMigrationJobTotals(
			ctx, jobID, opts.jobBase.RowsMigrated+result.RowsMigrated, opts.jobBase.TablesDone,
		)
	}
}
