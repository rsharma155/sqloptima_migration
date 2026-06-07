// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package planner

import (
	"time"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
)

// DateBounds holds the inclusive [Min, Max] date range for a date-partitioned table.
type DateBounds struct {
	Min time.Time // inclusive lower bound (truncated to day)
	Max time.Time // inclusive upper bound (truncated to day)
}

// IsEmpty returns true when Max is before Min (empty date range).
func (b DateBounds) IsEmpty() bool { return b.Max.Before(b.Min) }

// DateChunker splits a date range into chunks spanning daysPerChunk days each.
// Useful for tables without an integer PK but with a monotonic date column.
type DateChunker struct {
	daysPerChunk int
}

// NewDateChunker creates a date chunker. daysPerChunk is forced to at least 1.
func NewDateChunker(daysPerChunk int) *DateChunker {
	if daysPerChunk < 1 {
		daysPerChunk = 1
	}
	return &DateChunker{daysPerChunk: daysPerChunk}
}

// Plan produces ChunkPlans covering [bounds.Min, bounds.Max] in date steps.
// start_key and end_key in each plan are ISO-8601 date strings "YYYY-MM-DD".
func (c *DateChunker) Plan(jobID core.JobID, schema, table, dateCol string,
	bounds DateBounds) []core.ChunkPlan {

	if bounds.IsEmpty() {
		return nil
	}

	var plans []core.ChunkPlan
	var idx uint32
	start := truncateToDay(bounds.Min)
	maxDay := truncateToDay(bounds.Max)
	step := time.Duration(c.daysPerChunk-1) * 24 * time.Hour

	for !start.After(maxDay) {
		end := start.Add(step)
		if end.After(maxDay) {
			end = maxDay
		}
		end = truncateToDay(end)

		sk := start.Format("2006-01-02")
		ek := end.Format("2006-01-02")
		plans = append(plans, core.NewChunkPlan(jobID, schema, table, idx, dateCol, &sk, &ek))
		idx++

		next := end.AddDate(0, 0, 1)
		if !next.After(maxDay) {
			start = next
		} else {
			break
		}
	}
	return plans
}

func truncateToDay(t time.Time) time.Time {
	return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, t.Location())
}
