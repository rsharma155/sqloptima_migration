// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"sync/atomic"

	"github.com/google/uuid"
	"golang.org/x/sync/errgroup"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
	"github.com/ravisharma/sql-optima/engine-go/internal/extractor"
	"github.com/ravisharma/sql-optima/engine-go/internal/planner"
)

// moveParallel runs chunk groups concurrently with a worker pool capped at numWorkers.
// Each goroutine owns a dedicated MigrationChunkPipeline (separate SQL Server connections per chunk).
func (m *MigrationTableDataMover) moveParallel(
	ctx context.Context,
	jobID uuid.UUID,
	src extractor.SQLServerConfig,
	pgURL string,
	table GoTableDispatchPayload,
	chunks []core.ChunkPlan,
	schema extractor.ExtractionSchema,
	transforms *MigrationColumnTransformPipeline,
	numWorkers int,
	opts tableMoveOptions,
	tableSizer *planner.AdaptiveChunkSizer,
) (MoveTableResult, error) {
	result := MoveTableResult{TableName: table.TableName}

	if m.runtime.Queue != nil {
		return m.moveParallelQueued(ctx, jobID, src, pgURL, table, schema, transforms, numWorkers, opts, tableSizer)
	}

	partitions := PartitionChunks(chunks, numWorkers)
	if len(partitions) == 0 {
		return result, nil
	}

	var totalRows atomic.Int64
	var totalChunks atomic.Int32

	g, gctx := errgroup.WithContext(ctx)
	g.SetLimit(numWorkers)

	var progressMu sync.Mutex

	for workerIdx, partition := range partitions {
		workerIdx := workerIdx
		partition := partition
		g.Go(func() error {
			pipeline := NewMigrationChunkPipeline(src, pgURL)
			workerSizer := tableSizer.Clone()
			var partRows int64

			for _, chunk := range partition {
				if err := gctx.Err(); err != nil {
					return err
				}
				if m.command != nil {
					if err := m.command.CheckBeforeChunk(gctx); err != nil {
						return err
					}
				}
				outcome, err := m.executeChunk(gctx, pipeline, chunk, table, schema, transforms, opts)
				if err != nil {
					_ = m.handleChunkFailure(gctx, jobID, table, chunk, workerSizer, err)
					return fmt.Errorf("worker %d chunk %d: %w", workerIdx, chunk.ChunkIndex, err)
				}
				if workerSizer != nil {
					workerSizer.NextSize(outcome.durMs)
				}
				partRows += outcome.rows

				totalRows.Add(outcome.rows)
				totalChunks.Add(1)

				progressMu.Lock()
				_ = m.meta.UpdateTablePlanProgress(
					gctx, jobID, table.TableName, "migrating", totalRows.Load(),
				)
				progressMu.Unlock()
			}
			return nil
		})
	}

	if err := g.Wait(); err != nil {
		if errors.Is(err, ErrJobStopped) {
			_ = m.meta.UpdateTablePlanProgress(ctx, jobID, table.TableName, "stopped", totalRows.Load())
		} else {
			_ = m.meta.UpdateTablePlanProgress(ctx, jobID, table.TableName, "failed", totalRows.Load())
		}
		return result, err
	}

	result.RowsMigrated = totalRows.Load()
	result.ChunksRun = int(totalChunks.Load())
	return result, nil
}

func (m *MigrationTableDataMover) moveParallelQueued(
	ctx context.Context,
	jobID uuid.UUID,
	src extractor.SQLServerConfig,
	pgURL string,
	table GoTableDispatchPayload,
	schema extractor.ExtractionSchema,
	transforms *MigrationColumnTransformPipeline,
	numWorkers int,
	opts tableMoveOptions,
	tableSizer *planner.AdaptiveChunkSizer,
) (MoveTableResult, error) {
	result := MoveTableResult{TableName: table.TableName}
	var totalRows atomic.Int64
	var totalChunks atomic.Int32

	g, gctx := errgroup.WithContext(ctx)
	g.SetLimit(numWorkers)

	var progressMu sync.Mutex

	for w := 0; w < numWorkers; w++ {
		g.Go(func() error {
			pipeline := NewMigrationChunkPipeline(src, pgURL)
			workerSizer := tableSizer.Clone()

			for {
				if err := gctx.Err(); err != nil {
					return err
				}
				if m.command != nil {
					if err := m.command.CheckBeforeChunk(gctx); err != nil {
						return err
					}
				}
				chunk, err := m.claimNextTableChunk(jobID, table.SourceSchema, table.TableName)
				if err != nil {
					return err
				}
				if chunk == nil {
					return nil
				}
				outcome, err := m.executeChunk(gctx, pipeline, *chunk, table, schema, transforms, opts)
				if err != nil {
					_ = m.handleChunkFailure(gctx, jobID, table, *chunk, workerSizer, err)
					return fmt.Errorf("chunk %d: %w", chunk.ChunkIndex, err)
				}
				m.recordChunkSuccess(jobID, table, *chunk, workerSizer, outcome)

				totalRows.Add(outcome.rows)
				totalChunks.Add(1)

				progressMu.Lock()
				_ = m.meta.UpdateTablePlanProgress(
					gctx, jobID, table.TableName, "migrating", totalRows.Load(),
				)
				progressMu.Unlock()
			}
		})
	}

	if err := g.Wait(); err != nil {
		if errors.Is(err, ErrJobStopped) {
			_ = m.meta.UpdateTablePlanProgress(ctx, jobID, table.TableName, "stopped", totalRows.Load())
		} else {
			_ = m.meta.UpdateTablePlanProgress(ctx, jobID, table.TableName, "failed", totalRows.Load())
		}
		return result, err
	}

	result.RowsMigrated = totalRows.Load()
	result.ChunksRun = int(totalChunks.Load())
	return result, nil
}
