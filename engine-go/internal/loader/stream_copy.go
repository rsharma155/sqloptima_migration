// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package loader

import (
	"context"
	"fmt"
	"io"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
	"github.com/ravisharma/sql-optima/engine-go/internal/extractor"
)

// RowProgressFunc is invoked as rows are encoded for COPY (may be throttled by caller).
type RowProgressFunc func(rowsWritten int64)

// copyFromReader performs a PostgreSQL binary COPY FROM STDIN using a streaming reader.
type copyFromReader func(ctx context.Context, r io.Reader) error

// streamBinaryCopyFromChannel encodes rows into the binary COPY wire format on a
// background goroutine and streams them to PostgreSQL without buffering the full chunk.
func streamBinaryCopyFromChannel(
	ctx context.Context,
	copyFrom copyFromReader,
	fieldCount int,
	schema extractor.ExtractionSchema,
	in <-chan []core.CellValue,
	onProgress RowProgressFunc,
) (int64, error) {
	pr, pw := io.Pipe()

	type pipeResult struct {
		rows int64
		err  error
	}
	encodeDone := make(chan pipeResult, 1)

	go func() {
		rows, err := encodeBinaryCopyToWriter(pw, fieldCount, schema, in, onProgress)
		closeErr := pw.CloseWithError(err)
		if err == nil && closeErr != nil {
			err = closeErr
		}
		encodeDone <- pipeResult{rows: rows, err: err}
	}()

	copyErr := copyFrom(ctx, pr)
	_ = pr.Close()

	enc := <-encodeDone
	if copyErr != nil {
		return enc.rows, fmt.Errorf("COPY: %w", copyErr)
	}
	if enc.err != nil {
		return enc.rows, enc.err
	}
	return enc.rows, nil
}

func encodeBinaryCopyToWriter(
	w io.Writer,
	fieldCount int,
	schema extractor.ExtractionSchema,
	in <-chan []core.CellValue,
	onProgress RowProgressFunc,
) (int64, error) {
	if err := writeBinaryCopyHeader(w); err != nil {
		return 0, fmt.Errorf("write COPY header: %w", err)
	}

	var rows int64
	for cells := range in {
		row, err := CellsToCopyRow(schema, cells)
		if err != nil {
			return rows, fmt.Errorf("encode row: %w", err)
		}
		if err := writeBinaryCopyRow(w, fieldCount, row); err != nil {
			return rows, fmt.Errorf("write row: %w", err)
		}
		rows++
		if onProgress != nil {
			onProgress(rows)
		}
	}
	if err := writeBinaryCopyTrailer(w); err != nil {
		return rows, fmt.Errorf("write COPY trailer: %w", err)
	}
	return rows, nil
}

func writeBinaryCopyHeader(w io.Writer) error {
	buf := append([]byte(nil), pgCopySignature[:]...)
	buf = appendInt32BE(buf, 0)
	buf = appendInt32BE(buf, 0)
	_, err := w.Write(buf)
	return err
}

func writeBinaryCopyRow(w io.Writer, fieldCount int, values []CopyValue) error {
	if len(values) != fieldCount {
		return fmt.Errorf("row arity mismatch: expected %d fields, got %d",
			fieldCount, len(values))
	}
	rowBuf := appendInt16BE(make([]byte, 0, 64), int16(fieldCount))
	for _, v := range values {
		data := v.copyDataBytes()
		if data == nil {
			rowBuf = appendInt32BE(rowBuf, -1)
		} else {
			rowBuf = appendInt32BE(rowBuf, int32(len(data)))
			rowBuf = append(rowBuf, data...)
		}
	}
	_, err := w.Write(rowBuf)
	return err
}

func writeBinaryCopyTrailer(w io.Writer) error {
	_, err := w.Write(appendInt16BE(make([]byte, 0, 2), -1))
	return err
}
