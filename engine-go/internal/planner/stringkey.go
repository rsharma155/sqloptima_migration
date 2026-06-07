// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package planner

import (
	"github.com/ravisharma/sql-optima/engine-go/internal/core"
)

// StringBounds holds lexicographic inclusive bounds for a text/varchar PK column.
type StringBounds struct {
	Min string
	Max string
}

func (b StringBounds) IsEmpty() bool {
	if b.Min == "" && b.Max == "" {
		return true
	}
	return b.Min > b.Max
}

// StringChunker plans a single inclusive range chunk for text PK columns.
// Mirrors the Python chunk planner fallback for non-numeric key types.
type StringChunker struct{}

func (StringChunker) Plan(jobID core.JobID, schema, table, col string, bounds StringBounds) []core.ChunkPlan {
	if bounds.IsEmpty() {
		return nil
	}
	sk, ek := bounds.Min, bounds.Max
	return []core.ChunkPlan{
		core.NewChunkPlan(jobID, schema, table, 0, col, &sk, &ek),
	}
}
