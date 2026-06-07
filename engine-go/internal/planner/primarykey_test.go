// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package planner_test

import (
	"strconv"
	"testing"

	"github.com/google/uuid"
	"github.com/ravisharma/sql-optima/engine-go/internal/planner"
)

func planPKRanges(min, max, size int64) [][2]string {
	c := planner.NewPrimaryKeyChunker(size)
	plans := c.Plan(uuid.New(), "dbo", "orders", "id",
		planner.PrimaryKeyBounds{Min: min, Max: max})
	out := make([][2]string, len(plans))
	for i, p := range plans {
		out[i] = [2]string{*p.StartKey, *p.EndKey}
	}
	return out
}

func TestSingleChunkWhenRangeFits(t *testing.T) {
	ranges := planPKRanges(1, 500, 1_000)
	if len(ranges) != 1 || ranges[0] != [2]string{"1", "500"} {
		t.Errorf("expected single chunk (1,500), got %v", ranges)
	}
}

func TestExactMultipleProducesEvenChunks(t *testing.T) {
	ranges := planPKRanges(1, 3000, 1_000)
	want := [][2]string{{"1", "1000"}, {"1001", "2000"}, {"2001", "3000"}}
	assertRanges(t, ranges, want)
}

func TestRemainderGoesIntoFinalSmallerChunk(t *testing.T) {
	ranges := planPKRanges(1, 2500, 1_000)
	want := [][2]string{{"1", "1000"}, {"1001", "2000"}, {"2001", "2500"}}
	assertRanges(t, ranges, want)
}

func TestRangesAreContiguousAndNonOverlapping(t *testing.T) {
	c := planner.NewPrimaryKeyChunker(100)
	plans := c.Plan(uuid.New(), "dbo", "t", "id",
		planner.PrimaryKeyBounds{Min: 0, Max: 1_000})

	var expectedNext int64
	for _, p := range plans {
		start, _ := strconv.ParseInt(*p.StartKey, 10, 64)
		end, _ := strconv.ParseInt(*p.EndKey, 10, 64)
		if start != expectedNext {
			t.Fatalf("gap or overlap: expected start %d, got %d", expectedNext, start)
		}
		expectedNext = end + 1
	}
	if expectedNext != 1001 {
		t.Errorf("final chunk must reach max+1=1001, got %d", expectedNext)
	}
}

func TestChunkIndexIncrements(t *testing.T) {
	c := planner.NewPrimaryKeyChunker(1_000)
	plans := c.Plan(uuid.New(), "dbo", "t", "id",
		planner.PrimaryKeyBounds{Min: 1, Max: 5_000})
	for i, p := range plans {
		if p.ChunkIndex != uint32(i) {
			t.Errorf("chunk index[%d] = %d, want %d", i, p.ChunkIndex, i)
		}
	}
}

func TestEmptyTableProducesNoChunks(t *testing.T) {
	ranges := planPKRanges(1, 0, 1_000) // max < min = empty
	if len(ranges) != 0 {
		t.Errorf("empty table must produce zero chunks, got %d", len(ranges))
	}
}

func TestNegativeKeyRangeSupported(t *testing.T) {
	ranges := planPKRanges(-500, 500, 500)
	want := [][2]string{{"-500", "-1"}, {"0", "499"}, {"500", "500"}}
	assertRanges(t, ranges, want)
}

func TestSingleRowTable(t *testing.T) {
	ranges := planPKRanges(42, 42, 1_000)
	if len(ranges) != 1 || ranges[0] != [2]string{"42", "42"} {
		t.Errorf("single-row table: expected [(42,42)], got %v", ranges)
	}
}

func TestZeroChunkSizeCoercedToOne(t *testing.T) {
	c := planner.NewPrimaryKeyChunker(0)
	plans := c.Plan(uuid.New(), "dbo", "t", "id",
		planner.PrimaryKeyBounds{Min: 1, Max: 3})
	// size coerced to 1 → 3 single-key chunks
	if len(plans) != 3 {
		t.Errorf("expected 3 single-key chunks, got %d", len(plans))
	}
}

func TestHundredMillionRowsChunked(t *testing.T) {
	c := planner.NewPrimaryKeyChunker(100_000)
	plans := c.Plan(uuid.New(), "dbo", "big", "id",
		planner.PrimaryKeyBounds{Min: 1, Max: 100_000_000})
	if len(plans) != 1_000 {
		t.Errorf("expected 1000 chunks, got %d", len(plans))
	}
	if plans[0].QualifiedTable() != "dbo.big" {
		t.Errorf("QualifiedTable() = %q, want %q", plans[0].QualifiedTable(), "dbo.big")
	}
}

func assertRanges(t *testing.T, got [][2]string, want [][2]string) {
	t.Helper()
	if len(got) != len(want) {
		t.Fatalf("len(ranges) = %d, want %d; ranges: %v", len(got), len(want), got)
	}
	for i, w := range want {
		if got[i] != w {
			t.Errorf("ranges[%d] = %v, want %v", i, got[i], w)
		}
	}
}
