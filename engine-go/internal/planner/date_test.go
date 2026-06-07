// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package planner_test

import (
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/ravisharma/sql-optima/engine-go/internal/planner"
)

func d(s string) time.Time {
	t, _ := time.Parse("2006-01-02", s)
	return t
}

func planDateRanges(min, max string, days int) [][2]string {
	c := planner.NewDateChunker(days)
	plans := c.Plan(uuid.New(), "dbo", "events", "event_date",
		planner.DateBounds{Min: d(min), Max: d(max)})
	out := make([][2]string, len(plans))
	for i, p := range plans {
		out[i] = [2]string{*p.StartKey, *p.EndKey}
	}
	return out
}

func TestSingleChunkWhenSpanFits(t *testing.T) {
	ranges := planDateRanges("2026-01-01", "2026-01-05", 30)
	if len(ranges) != 1 || ranges[0] != [2]string{"2026-01-01", "2026-01-05"} {
		t.Errorf("single chunk expected, got %v", ranges)
	}
}

func TestWeeklyChunksAreContiguous(t *testing.T) {
	ranges := planDateRanges("2026-01-01", "2026-01-21", 7)
	want := [][2]string{
		{"2026-01-01", "2026-01-07"},
		{"2026-01-08", "2026-01-14"},
		{"2026-01-15", "2026-01-21"},
	}
	assertRanges(t, ranges, want)
}

func TestPartialFinalChunk(t *testing.T) {
	ranges := planDateRanges("2026-01-01", "2026-01-10", 7)
	want := [][2]string{
		{"2026-01-01", "2026-01-07"},
		{"2026-01-08", "2026-01-10"},
	}
	assertRanges(t, ranges, want)
}

func TestSingleDayRange(t *testing.T) {
	ranges := planDateRanges("2026-06-01", "2026-06-01", 7)
	if len(ranges) != 1 || ranges[0] != [2]string{"2026-06-01", "2026-06-01"} {
		t.Errorf("single-day range: expected 1 chunk, got %v", ranges)
	}
}

func TestEmptyDateRangeProducesNoChunks(t *testing.T) {
	ranges := planDateRanges("2026-06-02", "2026-06-01", 7)
	if len(ranges) != 0 {
		t.Errorf("inverted range must produce no chunks, got %v", ranges)
	}
}

func TestCrossesMonthBoundary(t *testing.T) {
	ranges := planDateRanges("2026-01-30", "2026-02-03", 2)
	want := [][2]string{
		{"2026-01-30", "2026-01-31"},
		{"2026-02-01", "2026-02-02"},
		{"2026-02-03", "2026-02-03"},
	}
	assertRanges(t, ranges, want)
}

func TestRangesHaveNoGaps(t *testing.T) {
	c := planner.NewDateChunker(10)
	plans := c.Plan(uuid.New(), "dbo", "events", "event_date",
		planner.DateBounds{Min: d("2026-01-01"), Max: d("2026-03-31")})
	for i := 1; i < len(plans); i++ {
		prevEnd, _ := time.Parse("2006-01-02", *plans[i-1].EndKey)
		nextStart, _ := time.Parse("2006-01-02", *plans[i].StartKey)
		if nextStart != prevEnd.AddDate(0, 0, 1) {
			t.Errorf("gap between chunk %d end=%s and chunk %d start=%s",
				i-1, *plans[i-1].EndKey, i, *plans[i].StartKey)
		}
	}
}

func TestZeroDaysCoercedToOne(t *testing.T) {
	ranges := planDateRanges("2026-01-01", "2026-01-03", 0)
	if len(ranges) != 3 {
		t.Errorf("zero days-per-chunk must produce 3 daily chunks, got %d", len(ranges))
	}
}
