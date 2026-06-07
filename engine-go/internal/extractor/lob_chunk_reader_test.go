// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package extractor_test

import (
	"strings"
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
	"github.com/ravisharma/sql-optima/engine-go/internal/extractor"
)

func TestBuildLOBSubstringQueryUsesParams(t *testing.T) {
	sql := extractor.BuildLOBSubstringQuery("dbo", "files", "content", "id")
	if !strings.Contains(sql, "SUBSTRING([content], @P1, @P2)") {
		t.Fatalf("unexpected query: %s", sql)
	}
	if !strings.Contains(sql, "WHERE [id] = @P3") {
		t.Fatalf("missing pk predicate: %s", sql)
	}
}

func TestSplitSchemaForLOBStreaming(t *testing.T) {
	schema := extractor.ExtractionSchema{Columns: []extractor.ExtractionColumn{
		{Name: "id", LogicalType: core.LogicalInt64},
		{Name: "body", LogicalType: core.LogicalLargeUtf8},
		{Name: "name", LogicalType: core.LogicalUtf8},
	}}
	qSchema, lobIdx := extractor.SplitSchemaForLOBStreaming(schema, "id", extractor.ExtractOptions{})
	if len(lobIdx) != 1 || lobIdx[0] != 1 {
		t.Fatalf("lob indexes = %v", lobIdx)
	}
	names := qSchema.ColumnNames()
	if len(names) != 2 || names[0] != "id" || names[1] != "name" {
		t.Fatalf("query columns = %v", names)
	}
}

func TestSplitSchemaNoLOBPassthrough(t *testing.T) {
	schema := extractor.ExtractionSchema{Columns: []extractor.ExtractionColumn{
		{Name: "id", LogicalType: core.LogicalInt64},
	}}
	qSchema, lobIdx := extractor.SplitSchemaForLOBStreaming(schema, "id", extractor.ExtractOptions{})
	if len(lobIdx) != 0 || len(qSchema.Columns) != 1 {
		t.Fatalf("expected passthrough, got lob=%v cols=%d", lobIdx, len(qSchema.Columns))
	}
}

func TestSplitSchemaInlineBinaryLOBs(t *testing.T) {
	schema := extractor.ExtractionSchema{Columns: []extractor.ExtractionColumn{
		{Name: "id", LogicalType: core.LogicalInt64},
		{Name: "body", LogicalType: core.LogicalLargeUtf8},
		{Name: "blob", LogicalType: core.LogicalLargeBinary},
	}}
	qSchema, lobIdx := extractor.SplitSchemaForLOBStreaming(schema, "id", extractor.ExtractOptions{
		InlineTextLOBs:   true,
		InlineBinaryLOBs: true,
	})
	if len(lobIdx) != 0 {
		t.Fatalf("expected no streaming LOBs, got %v", lobIdx)
	}
	if len(qSchema.Columns) != 3 {
		t.Fatalf("query columns = %d want 3 (all inline)", len(qSchema.Columns))
	}
}

func TestSplitSchemaInlineTextLOBs(t *testing.T) {
	schema := extractor.ExtractionSchema{Columns: []extractor.ExtractionColumn{
		{Name: "id", LogicalType: core.LogicalInt64},
		{Name: "body", LogicalType: core.LogicalLargeUtf8},
		{Name: "blob", LogicalType: core.LogicalLargeBinary},
	}}
	qSchema, lobIdx := extractor.SplitSchemaForLOBStreaming(schema, "id", extractor.ExtractOptions{InlineTextLOBs: true})
	if len(lobIdx) != 1 || lobIdx[0] != 2 {
		t.Fatalf("lob indexes = %v", lobIdx)
	}
	if len(qSchema.Columns) != 2 {
		t.Fatalf("query columns = %d want 2 (id + body inline)", len(qSchema.Columns))
	}
}
