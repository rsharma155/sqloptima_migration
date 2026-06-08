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

// RunToTargetTable streams rows into a specific PostgreSQL schema.table via binary COPY.
func (l *Loader) RunToTargetTable(
	ctx context.Context,
	targetSchema, targetTable string,
	schema extractor.ExtractionSchema,
	in <-chan []core.CellValue,
	onProgress RowProgressFunc,
) (int64, error) {
	conn, err := pgx.Connect(ctx, l.pgURL)
	if err != nil {
		return 0, fmt.Errorf("pgx connect: %w", err)
	}
	defer conn.Close(ctx)

	copySQL := BuildCopyStatement(targetSchema, targetTable, schema.ColumnNames())
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
