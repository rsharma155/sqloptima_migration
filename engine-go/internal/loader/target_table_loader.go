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

// RunToTargetTable streams rows into a specific PostgreSQL schema.table via binary COPY.
func (l *Loader) RunToTargetTable(
	ctx context.Context,
	targetSchema, targetTable string,
	schema extractor.ExtractionSchema,
	in <-chan []core.CellValue,
) (int64, error) {
	conn, err := pgx.Connect(ctx, l.pgURL)
	if err != nil {
		return 0, fmt.Errorf("pgx connect: %w", err)
	}
	defer conn.Close(ctx)

	copySQL := BuildCopyStatement(targetSchema, targetTable, schema.ColumnNames())
	enc := NewBinaryCopyEncoder(len(schema.Columns))

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
	_, err = conn.PgConn().CopyFrom(ctx, bytes.NewReader(payload), copySQL)
	if err != nil {
		return 0, fmt.Errorf("COPY into %s.%s: %w", targetSchema, targetTable, err)
	}
	return enc.RowsWritten(), nil
}
