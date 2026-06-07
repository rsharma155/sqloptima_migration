// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package loader

import (
	"bytes"
	"context"
	"fmt"

	"github.com/jackc/pgx/v5"
	"github.com/ravisharma/sql-optima/engine-go/internal/core"
	"github.com/ravisharma/sql-optima/engine-go/internal/extractor"
)

// Loader streams a buffered binary COPY payload into PostgreSQL using pgx/v5's
// native CopyFrom support. It consumes from an in-memory channel populated by
// an Extractor goroutine (no intermediate Arrow IPC file).
//
// Usage:
//
//	rows, err := loader.Run(ctx, pgURL, chunk, schema, rowChannel)
type Loader struct {
	pgURL string
}

// New creates a Loader targeting the given PostgreSQL connection URL.
func New(pgURL string) *Loader { return &Loader{pgURL: pgURL} }

// Run reads all rows from in, encodes them as a PostgreSQL binary COPY payload,
// and sends the payload to PostgreSQL in a single COPY transaction.
//
// Returns the number of rows loaded and any error. The caller is responsible
// for closing the in channel after the extractor has finished.
//
// Integration tests cover this with a real PostgreSQL instance
// (build tag: integration).
func (l *Loader) Run(
	ctx context.Context,
	chunk core.ChunkPlan,
	schema extractor.ExtractionSchema,
	in <-chan []core.CellValue,
) (int64, error) {

	conn, err := pgx.Connect(ctx, l.pgURL)
	if err != nil {
		return 0, fmt.Errorf("pgx connect: %w", err)
	}
	defer conn.Close(ctx)

	copySQL := BuildCopyStatement(chunk.TableSchema, chunk.TableName, schema.ColumnNames())
	enc := NewBinaryCopyEncoder(len(schema.Columns))

	// Drain the channel and encode all rows.
	for cells := range in {
		row, err := CellsToCopyRow(schema, cells)
		if err != nil {
			return 0, fmt.Errorf("encode row: %w", err)
		}
		if err := enc.WriteRow(row); err != nil {
			return 0, fmt.Errorf("encode row: %w", err)
		}
	}

	payload := enc.Finish()

	// Stream the encoded payload to PostgreSQL via CopyFrom.
	_, err = conn.PgConn().CopyFrom(ctx, bytes.NewReader(payload), copySQL)
	if err != nil {
		return 0, fmt.Errorf("COPY into %s.%s: %w", chunk.TableSchema, chunk.TableName, err)
	}
	return enc.RowsWritten(), nil
}
