// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package extractor_test

import (
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
	"github.com/ravisharma/sql-optima/engine-go/internal/extractor"
)

func TestColumnNamesPreservesOrder(t *testing.T) {
	s := extractor.ExtractionSchema{
		Columns: []extractor.ExtractionColumn{
			{Name: "id", LogicalType: core.LogicalInt32},
			{Name: "name", LogicalType: core.LogicalUtf8},
			{Name: "body", LogicalType: core.LogicalLargeUtf8},
		},
	}
	got := s.ColumnNames()
	want := []string{"id", "name", "body"}
	for i, w := range want {
		if got[i] != w {
			t.Errorf("ColumnNames()[%d] = %q, want %q", i, got[i], w)
		}
	}
}

func TestFromTableMetaMapsTypes(t *testing.T) {
	meta := core.TableMeta{
		SchemaName: "dbo",
		TableName:  "orders",
		Columns: []core.ColumnMeta{
			{ColumnName: "id", DataType: "int", MaxLength: 4, IsNullable: false},
			{ColumnName: "note", DataType: "nvarchar", MaxLength: -1, IsNullable: true},
		},
	}
	s := extractor.FromTableMeta(meta)
	if len(s.Columns) != 2 {
		t.Fatalf("expected 2 columns, got %d", len(s.Columns))
	}
	if s.Columns[0].LogicalType != core.LogicalInt32 {
		t.Errorf("column 0 type = %v, want Int32", s.Columns[0].LogicalType)
	}
	if s.Columns[1].LogicalType != core.LogicalLargeUtf8 {
		t.Errorf("column 1 type = %v, want LargeUtf8", s.Columns[1].LogicalType)
	}
	if !s.Columns[1].IsNullable {
		t.Error("note column must be nullable")
	}
}
