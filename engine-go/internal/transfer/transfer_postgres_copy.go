// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package transfer

import (
	"context"
	"fmt"
	"io"

	"github.com/jackc/pgx/v5"
	"github.com/ravisharma/sql-optima/engine-go/internal/extractport"
	"github.com/ravisharma/sql-optima/engine-go/internal/loader"
)

// CopyPostgresTableText streams rows with COPY TO STDOUT → COPY FROM STDIN.
func CopyPostgresTableText(
	ctx context.Context,
	srcURL, tgtURL string,
	srcSchema, srcTable, tgtSchema, tgtTable string,
	columns []string,
) (int64, error) {
	selectSQL := extractport.BuildPostgresExtractQuery(srcSchema, srcTable, "", columns)
	copyOut := fmt.Sprintf("COPY (%s) TO STDOUT", selectSQL)
	copyIn := loader.BuildCopyStatement(tgtSchema, tgtTable, columns)
	// Text COPY is more tolerant of homogeneous type aliases than binary.
	copyIn = rewriteCopyAsText(copyIn)

	src, err := pgx.Connect(ctx, srcURL)
	if err != nil {
		return 0, fmt.Errorf("connect transfer source postgres: %w", err)
	}
	defer src.Close(ctx)

	tgt, err := pgx.Connect(ctx, tgtURL)
	if err != nil {
		return 0, fmt.Errorf("connect transfer target postgres: %w", err)
	}
	defer tgt.Close(ctx)

	pr, pw := io.Pipe()
	type copyResult struct {
		err error
	}
	srcDone := make(chan copyResult, 1)
	go func() {
		_, err := src.PgConn().CopyTo(ctx, pw, copyOut)
		closeErr := pw.CloseWithError(err)
		if err == nil {
			err = closeErr
		}
		srcDone <- copyResult{err: err}
	}()

	tag, copyErr := tgt.PgConn().CopyFrom(ctx, pr, copyIn)
	_ = pr.Close()
	srcRes := <-srcDone
	if copyErr != nil {
		return 0, fmt.Errorf("COPY FROM target: %w", copyErr)
	}
	if srcRes.err != nil {
		return 0, fmt.Errorf("COPY TO source: %w", srcRes.err)
	}
	return tag.RowsAffected(), nil
}

func rewriteCopyAsText(binaryCopySQL string) string {
	const needle = " FROM STDIN WITH (FORMAT binary)"
	const text = " FROM STDIN"
	if len(binaryCopySQL) >= len(needle) && binaryCopySQL[len(binaryCopySQL)-len(needle):] == needle {
		return binaryCopySQL[:len(binaryCopySQL)-len(needle)] + text
	}
	return binaryCopySQL
}
