// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
)

func TestBuildMigrationExtractionSchema_usesDispatchTypes(t *testing.T) {
	schema := BuildMigrationExtractionSchema(
		[]string{"Amount", "Note"},
		map[string]string{"Amount": "decimal(18,2)", "Note": "nvarchar(max)"},
	)
	if schema.Columns[0].LogicalType != core.LogicalDecimal {
		t.Fatalf("Amount: got %v want LogicalDecimal", schema.Columns[0].LogicalType)
	}
	if schema.Columns[1].LogicalType != core.LogicalLargeUtf8 {
		t.Fatalf("Note: got %v want LogicalLargeUtf8", schema.Columns[1].LogicalType)
	}
}

func TestNormalizeDispatchColumnType(t *testing.T) {
	if got := NormalizeDispatchColumnType(" decimal(10,2) "); got != "decimal" {
		t.Fatalf("got %q", got)
	}
}

func TestBuildMigrationExtractionSchema_boundedNvarcharNotLOB(t *testing.T) {
	schema := BuildMigrationExtractionSchema(
		[]string{"Code"},
		map[string]string{"Code": "nvarchar(50)"},
	)
	if schema.Columns[0].LogicalType != core.LogicalUtf8 {
		t.Fatalf("bounded nvarchar: got %v want LogicalUtf8", schema.Columns[0].LogicalType)
	}
}

func TestBuildMigrationExtractionSchema_intColumn(t *testing.T) {
	schema := BuildMigrationExtractionSchema(
		[]string{"BookingId"},
		map[string]string{"BookingId": "int"},
	)
	if schema.Columns[0].LogicalType != core.LogicalInt32 {
		t.Fatalf("int: got %v want LogicalInt32", schema.Columns[0].LogicalType)
	}
}
