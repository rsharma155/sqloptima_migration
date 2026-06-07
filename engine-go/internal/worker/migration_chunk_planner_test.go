// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/extractor"
)

func TestClassifySQLType(t *testing.T) {
	cases := map[string]ChunkKeyKind{
		"uniqueidentifier":       ChunkKeyUUID,
		"UNIQUEIDENTIFIER":       ChunkKeyUUID,
		"datetime2(7)":           ChunkKeyDateTime,
		"smalldatetime":          ChunkKeyDateTime,
		"date":                   ChunkKeyDateTime,
		"bigint":                 ChunkKeyInteger,
		"int":                    ChunkKeyInteger,
		"":                       ChunkKeyInteger,
	}
	for in, want := range cases {
		if got := classifySQLType(in); got != want {
			t.Errorf("classifySQLType(%q) = %v, want %v", in, got, want)
		}
	}
}

func TestBuildExtractOptions(t *testing.T) {
	table := GoTableDispatchPayload{
		WhereClause:  "active = 1",
		OrderColumn:  "created_at",
		SourceMaxDOP: 4,
	}
	opts := BuildExtractOptions(table, ChunkKeyInfo{Kind: ChunkKeyUUID}, true)
	if opts.WhereClause != "active = 1" || opts.OrderColumn != "created_at" || opts.MaxDOP != 4 {
		t.Fatalf("unexpected opts: %+v", opts)
	}
	if !opts.NoLock || !opts.UUIDKeyRange {
		t.Fatalf("expected nolock and uuid key range, got %+v", opts)
	}
}

func TestResolveConflictColumns(t *testing.T) {
	if got := ResolveConflictColumns([]string{"a", "b"}, ChunkKeyInfo{Column: "id"}); len(got) != 2 {
		t.Fatalf("job conflict override: %+v", got)
	}
	key := ChunkKeyInfo{Column: "id", Composite: []string{"tenant_id", "id"}}
	if got := ResolveConflictColumns(nil, key); len(got) != 2 || got[0] != "tenant_id" {
		t.Fatalf("composite pk: %+v", got)
	}
	if got := ResolveConflictColumns(nil, ChunkKeyInfo{Column: "id"}); len(got) != 1 || got[0] != "id" {
		t.Fatalf("single pk: %+v", got)
	}
}

func TestBuildExtractOptionsIntegerKey(t *testing.T) {
	opts := BuildExtractOptions(GoTableDispatchPayload{}, ChunkKeyInfo{Kind: ChunkKeyInteger}, false)
	if opts.UUIDKeyRange {
		t.Fatal("integer key must not set UUIDKeyRange")
	}
	_ = extractor.ExtractOptions{}
}
