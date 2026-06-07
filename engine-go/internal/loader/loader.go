// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package loader

import (
	"context"
	"fmt"
	"io"

	"github.com/jackc/pgx/v5"
	"github.com/ravisharma/sql-optima/engine-go/internal/core"
	"github.com/ravisharma/sql-optima/engine-go/internal/extractor"
)

// Loader streams rows into PostgreSQL using pgx/v5's native CopyFrom support.
//
// Usage:
//
//	rows, err := loader.Run(ctx, pgURL, chunk, schema, rowChannel, nil)
type Loader struct {
	pgURL string
}

// New creates a Loader targeting the given PostgreSQL connection URL.
func New(pgURL string) *Loader { return &Loader{pgURL: pgURL} }

// Run reads rows from in and streams them to PostgreSQL via binary COPY.
func (l *Loader) Run(
	ctx context.Context,
	chunk core.ChunkPlan,
	schema extractor.ExtractionSchema,
	in <-chan []core.CellValue,
	onProgress RowProgressFunc,
) (int64, error) {

	conn, err := pgx.Connect(ctx, l.pgURL)
	if err != nil {
		return 0, fmt.Errorf("pgx connect: %w", err)
	}
	defer conn.Close(ctx)

	copySQL := BuildCopyStatement(chunk.TableSchema, chunk.TableName, schema.ColumnNames())
	return streamBinaryCopyFromChannel(
		ctx,
		func(ctx context.Context, r io.Reader) error {
			_, err := conn.PgConn().CopyFrom(ctx, r, copySQL)
			return err
		},
		len(schema.Columns),
		schema,
		in,
		onProgress,
	)
}
