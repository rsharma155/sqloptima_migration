// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package planner_test

import (
	"testing"

	"github.com/google/uuid"

	"github.com/ravisharma/sql-optima/engine-go/internal/planner"
)

func TestUUIDChunker_producesBands(t *testing.T) {
	c := planner.UUIDChunker{}
	plans := c.Plan(
		uuid.New(), "dbo", "events", "event_id",
		planner.UUIDBounds{
			Min: "10000000-0000-0000-0000-000000000001",
			Max: "3fffffff-ffff-ffff-ffff-ffffffffffff",
		},
	)
	if len(plans) < 2 {
		t.Fatalf("expected multiple UUID bands, got %d", len(plans))
	}
	if plans[0].StartKey == nil || *plans[0].StartKey == "" {
		t.Fatal("missing start key")
	}
}

func TestUUIDChunker_emptyBounds(t *testing.T) {
	c := planner.UUIDChunker{}
	plans := c.Plan(uuid.New(), "dbo", "t", "id", planner.UUIDBounds{})
	if len(plans) != 0 {
		t.Fatalf("expected no plans, got %d", len(plans))
	}
}
