// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package planner

import "github.com/ravisharma/sql-optima/engine-go/internal/core"

// ChunkStrategy is the generic interface that all chunking algorithms implement.
// Implementations must guarantee:
//  1. Contiguity   — chunk ranges tile the whole key space with no gaps.
//  2. Non-overlap  — no key value belongs to two chunks.
//  3. Stable order — ChunkIndex increases monotonically from 0.
type ChunkStrategy[B any] interface {
	// Plan produces an ordered set of ChunkPlans covering bounds.
	Plan(jobID core.JobID, schema, table, pkColumn string, bounds B) []core.ChunkPlan
}

// PrimaryKeyBounds holds the inclusive integer min/max of an integer PK column.
// Obtained by the extractor via SELECT MIN(pk), MAX(pk) against the source table.
type PrimaryKeyBounds struct {
	Min int64
	Max int64
}

// IsEmpty returns true when Max < Min, which represents an empty table
// (MIN/MAX over zero rows returns NULL; the extractor converts NULL to 0/−1).
func (b PrimaryKeyBounds) IsEmpty() bool { return b.Max < b.Min }

// Cardinality returns the number of distinct key values in [Min, Max] inclusive.
func (b PrimaryKeyBounds) Cardinality() int64 {
	if b.IsEmpty() {
		return 0
	}
	return b.Max - b.Min + 1
}
