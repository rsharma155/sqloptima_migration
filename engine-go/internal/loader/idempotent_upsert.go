// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package loader

import (
	"context"
	"fmt"
	"hash/fnv"
	"io"

	"github.com/jackc/pgx/v5"
	"github.com/ravisharma/sql-optima/engine-go/internal/core"
	"github.com/ravisharma/sql-optima/engine-go/internal/extractor"
)

// RunToTargetTableUpsert loads rows via a temp staging table and merges with
// INSERT … ON CONFLICT DO UPDATE (mirrors Python copy_with_idempotent_write).
func (l *Loader) RunToTargetTableUpsert(
	ctx context.Context,
	targetSchema, targetTable string,
	conflictColumns []string,
	schema extractor.ExtractionSchema,
	in <-chan []core.CellValue,
) (int64, error) {
	conn, err := pgx.Connect(ctx, l.pgURL)
	if err != nil {
		return 0, fmt.Errorf("pgx connect: %w", err)
	}
	defer conn.Close(ctx)

	cols := schema.ColumnNames()
	if len(cols) == 0 {
		return 0, fmt.Errorf("empty column list for upsert")
	}
	if len(conflictColumns) == 0 {
		conflictColumns = []string{cols[0]}
	}

	staging := fmt.Sprintf("_mig_stg_%x", hashStrings(append([]string{targetSchema, targetTable}, conflictColumns...)...))

	target := fmt.Sprintf("%s.%s", quoteIdentPG(targetSchema), quoteIdentPG(targetTable))
	quotedCols := quoteColumnList(cols)

	tx, err := conn.Begin(ctx)
	if err != nil {
		return 0, fmt.Errorf("begin tx: %w", err)
	}
	defer tx.Rollback(ctx) //nolint:errcheck

	_, err = tx.Exec(ctx, fmt.Sprintf(
		`CREATE TEMP TABLE %s (LIKE %s INCLUDING DEFAULTS) ON COMMIT DROP`,
		quoteIdentPG(staging), target,
	))
	if err != nil {
		return 0, fmt.Errorf("create staging table: %w", err)
	}

	copySQL := BuildCopyStatement("", staging, cols)
	// Staging is in search_path; use unqualified name in COPY.
	copySQL = fmt.Sprintf("COPY %s (%s) FROM STDIN WITH (FORMAT binary)",
		quoteIdentPG(staging), quotedCols)

	rows, err := streamBinaryCopyFromChannel(
		ctx,
		func(ctx context.Context, r io.Reader) error {
			_, err := tx.Conn().PgConn().CopyFrom(ctx, r, copySQL)
			return err
		},
		len(schema.Columns),
		schema,
		in,
		nil,
	)
	if err != nil {
		return 0, fmt.Errorf("COPY into staging: %w", err)
	}

	updateSet := buildUpsertUpdateSet(cols)
	conflictList := quoteColumnList(conflictColumns)
	mergeSQL := fmt.Sprintf(
		`INSERT INTO %s (%s) SELECT %s FROM %s ON CONFLICT (%s) DO UPDATE SET %s`,
		target, quotedCols, quotedCols, quoteIdentPG(staging),
		conflictList, updateSet,
	)
	if _, err = tx.Exec(ctx, mergeSQL); err != nil {
		return 0, fmt.Errorf("upsert merge: %w", err)
	}
	if err = tx.Commit(ctx); err != nil {
		return 0, fmt.Errorf("commit upsert: %w", err)
	}
	return rows, nil
}

func quoteColumnList(cols []string) string {
	out := make([]string, len(cols))
	for i, c := range cols {
		out[i] = quoteIdentPG(c)
	}
	result := out[0]
	for i := 1; i < len(out); i++ {
		result += ", " + out[i]
	}
	return result
}

func buildUpsertUpdateSet(cols []string) string {
	if len(cols) == 0 {
		return ""
	}
	parts := make([]string, len(cols))
	for i, c := range cols {
		q := quoteIdentPG(c)
		parts[i] = fmt.Sprintf("%s = EXCLUDED.%s", q, q)
	}
	result := parts[0]
	for i := 1; i < len(parts); i++ {
		result += ", " + parts[i]
	}
	return result
}

func hashStrings(parts ...string) uint32 {
	h := fnv.New32a()
	for _, p := range parts {
		_, _ = h.Write([]byte(p))
		_, _ = h.Write([]byte{0})
	}
	return h.Sum32()
}
