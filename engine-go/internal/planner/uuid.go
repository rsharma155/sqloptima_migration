// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package planner

import (
	"strings"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
)

// UUIDBounds holds lexicographic inclusive UUID string bounds (CHAR(36) ordering).
type UUIDBounds struct {
	Min string
	Max string
}

func (b UUIDBounds) IsEmpty() bool {
	return b.Min == "" || b.Max == "" || strings.ToLower(b.Min) > strings.ToLower(b.Max)
}

// UUIDChunker splits a UUID PK range into hex-prefix bands (mirrors Python _generate_uuid_ranges).
type UUIDChunker struct{}

// Plan produces chunk plans intersecting [bounds.Min, bounds.Max] with 16 hex-prefix bands.
func (UUIDChunker) Plan(jobID core.JobID, schema, table, uuidCol string, bounds UUIDBounds) []core.ChunkPlan {
	if bounds.IsEmpty() {
		return nil
	}
	minVal := strings.ToLower(bounds.Min)
	maxVal := strings.ToLower(bounds.Max)

	var plans []core.ChunkPlan
	var idx uint32
	for _, ch := range "0123456789abcdef" {
		prefix := string(ch)
		bandStart := prefix + "0000000-0000-0000-0000-000000000000"
		bandEnd := prefix + "fffffff-ffff-ffff-ffff-ffffffffffff"
		effectiveStart := maxString(minVal, bandStart)
		effectiveEnd := minString(maxVal, bandEnd)
		if effectiveStart > effectiveEnd {
			continue
		}
		sk, ek := effectiveStart, effectiveEnd
		plans = append(plans, core.NewChunkPlan(jobID, schema, table, idx, uuidCol, &sk, &ek))
		idx++
	}
	if len(plans) == 0 {
		sk, ek := minVal, maxVal
		return []core.ChunkPlan{
			core.NewChunkPlan(jobID, schema, table, 0, uuidCol, &sk, &ek),
		}
	}
	return plans
}

func maxString(a, b string) string {
	if a > b {
		return a
	}
	return b
}

func minString(a, b string) string {
	if a < b {
		return a
	}
	return b
}
