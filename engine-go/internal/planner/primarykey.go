// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package planner

import (
	"fmt"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
)

// PrimaryKeyChunker splits an integer primary-key range [Min, Max] into
// contiguous, non-overlapping chunks of at most chunkSize keys each.
//
// start_key and end_key in the produced ChunkPlans are inclusive string-encoded
// integers, matching the BETWEEN @start AND @end extraction predicate used by
// the extractor query builder.
type PrimaryKeyChunker struct {
	chunkSize int64
}

// NewPrimaryKeyChunker creates a chunker. size is coerced to a minimum of 1
// to prevent an infinite loop on zero or negative input.
func NewPrimaryKeyChunker(size int64) *PrimaryKeyChunker {
	if size < 1 {
		size = 1
	}
	return &PrimaryKeyChunker{chunkSize: size}
}

// Plan produces ChunkPlans covering [bounds.Min, bounds.Max].
// Returns nil for an empty table (bounds.IsEmpty() == true).
func (c *PrimaryKeyChunker) Plan(jobID core.JobID, schema, table, pkCol string,
	bounds PrimaryKeyBounds) []core.ChunkPlan {

	if bounds.IsEmpty() {
		return nil
	}

	var plans []core.ChunkPlan
	var idx uint32
	start := bounds.Min

	for start <= bounds.Max {
		end := start + c.chunkSize - 1
		if end > bounds.Max {
			end = bounds.Max
		}

		sk := fmt.Sprintf("%d", start)
		ek := fmt.Sprintf("%d", end)
		plans = append(plans, core.NewChunkPlan(jobID, schema, table, idx, pkCol, &sk, &ek))
		idx++

		if end >= bounds.Max {
			break
		}
		start = end + 1
	}
	return plans
}
