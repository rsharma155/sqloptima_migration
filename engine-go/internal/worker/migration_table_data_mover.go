// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"context"
	"fmt"

	"github.com/google/uuid"

	"github.com/ravisharma/sql-optima/engine-go/internal/extractor"
)

// MigrationTableDataMover executes chunked extract→load for one table.
type MigrationTableDataMover struct {
	meta            MigrationMetadataPort
	chunkSize       int64
	command         *MigrationJobCommandController
	idempotent      bool
	conflictColumns []string
	useNoLock       bool
	runtime         MigrationEngineRuntime
}

func NewMigrationTableDataMover(meta MigrationMetadataPort, chunkSize int64) *MigrationTableDataMover {
	return NewMigrationTableDataMoverFull(meta, chunkSize, nil, false, nil, false, MigrationEngineRuntime{})
}

func NewMigrationTableDataMoverWithOptions(
	meta MigrationMetadataPort,
	chunkSize int64,
	command *MigrationJobCommandController,
	idempotent bool,
) *MigrationTableDataMover {
	return NewMigrationTableDataMoverFull(meta, chunkSize, command, idempotent, nil, false, MigrationEngineRuntime{})
}

func NewMigrationTableDataMoverFull(
	meta MigrationMetadataPort,
	chunkSize int64,
	command *MigrationJobCommandController,
	idempotent bool,
	conflictColumns []string,
	useNoLock bool,
	runtime MigrationEngineRuntime,
) *MigrationTableDataMover {
	if chunkSize < 1 {
		chunkSize = 10_000
	}
	return &MigrationTableDataMover{
		meta:            meta,
		chunkSize:       chunkSize,
		command:         command,
		idempotent:      idempotent,
		conflictColumns: append([]string(nil), conflictColumns...),
		useNoLock:       useNoLock,
		runtime:         runtime,
	}
}

// MoveTableResult summarises one table migration.
type MoveTableResult struct {
	TableName    string
	RowsMigrated int64
	ChunksRun    int
}

// Move executes PK-chunked data movement for a single dispatched table.
func (m *MigrationTableDataMover) Move(
	ctx context.Context,
	jobID uuid.UUID,
	src extractor.SQLServerConfig,
	pgURL string,
	table GoTableDispatchPayload,
) (MoveTableResult, error) {
	result := MoveTableResult{TableName: table.TableName}
	_ = m.meta.UpdateTablePlanProgress(ctx, jobID, table.TableName, "migrating", 0)

	tableSizer := m.newTableSizer(table)
	chunkSize := m.planChunkSize(table, tableSizer)

	chunks, key, err := ResolveTableChunks(ctx, jobID, src, table, chunkSize)
	if err != nil {
		return result, err
	}
	if m.runtime.Queue != nil {
		if err := ensureTableChunksEnqueued(m.runtime.Queue, jobID, table.SourceSchema, table.TableName, chunks); err != nil {
			return result, fmt.Errorf("enqueue chunks: %w", err)
		}
	}
	if len(chunks) == 0 {
		_ = m.meta.AppendMigrationJobLog(ctx, jobID, "info",
			fmt.Sprintf("Table %s is empty — 0 rows migrated", table.TableName))
		_ = m.meta.UpdateTablePlanProgress(ctx, jobID, table.TableName, "completed", 0)
		return result, nil
	}

	schema := BuildMigrationExtractionSchema(table.Columns, table.ColumnTypes)
	transforms := BuildColumnTransformPipeline(table)
	extractOpts := BuildExtractOptions(table, key, m.useNoLock)
	conflictCols := ResolveConflictColumns(m.conflictColumns, key)

	if len(key.Composite) > 1 {
		_ = m.meta.AppendMigrationJobLog(ctx, jobID, "info",
			fmt.Sprintf("Composite PK chunking for %s on column %s (%d key column(s))",
				table.TableName, key.Column, len(key.Composite)))
	}

	workers := effectiveParallelWorkers(table.ParallelWorkers)
	useParallel := isParallelChunkedStrategy(table.Strategy) && workers > 1

	runOpts := tableMoveOptions{
		conflictColumns: conflictCols,
		extractOpts:     extractOpts,
	}

	if useParallel {
		_ = m.meta.AppendMigrationJobLog(ctx, jobID, "info",
			fmt.Sprintf("Parallel migration for %s — %d worker(s), %d chunk(s)",
				table.TableName, workers, len(chunks)))
		result, err = m.moveParallel(ctx, jobID, src, pgURL, table, chunks, schema, transforms, workers, runOpts, tableSizer)
	} else {
		result, err = m.moveSequential(ctx, jobID, src, pgURL, table, chunks, schema, transforms, runOpts, tableSizer)
	}
	if err != nil {
		return result, err
	}

	_ = m.meta.AppendMigrationJobLog(ctx, jobID, "success",
		fmt.Sprintf("Completed %s: %d row(s) migrated in %d chunk(s)",
			table.TableName, result.RowsMigrated, result.ChunksRun))
	_ = m.meta.UpdateTablePlanProgress(ctx, jobID, table.TableName, "completed", result.RowsMigrated)
	return result, nil
}

type tableMoveOptions struct {
	conflictColumns []string
	extractOpts     extractor.ExtractOptions
}
