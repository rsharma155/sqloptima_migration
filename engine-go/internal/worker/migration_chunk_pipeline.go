// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"context"
	"fmt"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
	"github.com/ravisharma/sql-optima/engine-go/internal/extractor"
	"github.com/ravisharma/sql-optima/engine-go/internal/loader"
)

// MigrationChunkPipeline extracts one chunk from SQL Server and loads it into PostgreSQL.
type MigrationChunkPipeline struct {
	Extractor *extractor.Extractor
	Loader    *loader.Loader
}

func NewMigrationChunkPipeline(
	src extractor.SQLServerConfig, pgURL string,
) *MigrationChunkPipeline {
	return &MigrationChunkPipeline{
		Extractor: extractor.New(src),
		Loader:    loader.New(pgURL),
	}
}

// Run moves rows for a single chunk into the target schema.table.
func (p *MigrationChunkPipeline) Run(
	ctx context.Context,
	chunk core.ChunkPlan,
	targetSchema, targetTable string,
	schema extractor.ExtractionSchema,
	idempotent bool,
	conflictColumns []string,
	extractOpts extractor.ExtractOptions,
	transforms *MigrationColumnTransformPipeline,
) (int64, error) {
	pipe := make(chan []core.CellValue, 32)
	errCh := make(chan error, 1)

	go func() {
		defer close(pipe)
		raw := make(chan []core.CellValue, 32)
		extractErr := make(chan error, 1)
		go func() {
			extractErr <- p.Extractor.RunWithOptions(ctx, chunk, schema, extractOpts, raw)
			close(raw)
		}()
		for cells := range raw {
			if transforms != nil {
				cells = transforms.ApplyWithSchema(schema, cells)
			}
			select {
			case pipe <- cells:
			case <-ctx.Done():
				return
			}
		}
		errCh <- <-extractErr
	}()

	if idempotent && len(conflictColumns) > 0 {
		rows, err := p.Loader.RunToTargetTableUpsert(ctx, targetSchema, targetTable, conflictColumns, schema, pipe)
		if extractErr := <-errCh; extractErr != nil {
			return 0, fmt.Errorf("extract chunk: %w", extractErr)
		}
		if err != nil {
			return 0, fmt.Errorf("load chunk: %w", err)
		}
		return rows, nil
	}

	rows, err := p.Loader.RunToTargetTable(ctx, targetSchema, targetTable, schema, pipe)
	if extractErr := <-errCh; extractErr != nil {
		return 0, fmt.Errorf("extract chunk: %w", extractErr)
	}
	if err != nil {
		return 0, fmt.Errorf("load chunk: %w", err)
	}
	return rows, nil
}
