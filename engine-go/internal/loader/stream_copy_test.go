// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package loader

import (
	"bytes"
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
	"github.com/ravisharma/sql-optima/engine-go/internal/extractor"
)

func TestEncodeBinaryCopyToWriter(t *testing.T) {
	schema := extractor.ExtractionSchema{Columns: []extractor.ExtractionColumn{
		{Name: "id", LogicalType: core.LogicalInt32},
		{Name: "name", LogicalType: core.LogicalUtf8},
	}}
	in := make(chan []core.CellValue, 2)
	in <- []core.CellValue{core.CellI32{V: 1}, core.CellStr{V: "alpha"}}
	in <- []core.CellValue{core.CellI32{V: 2}, core.CellStr{V: "beta"}}
	close(in)

	var payload bytes.Buffer
	rows, err := encodeBinaryCopyToWriter(&payload, len(schema.Columns), schema, in, nil)
	if err != nil {
		t.Fatalf("encode stream: %v", err)
	}
	if rows != 2 {
		t.Fatalf("rows = %d want 2", rows)
	}
	if len(payload.Bytes()) == 0 {
		t.Fatal("expected non-empty COPY payload")
	}
}
