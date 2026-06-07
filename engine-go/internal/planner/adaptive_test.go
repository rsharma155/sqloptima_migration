// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package planner_test

import (
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/planner"
)

// helper: initial=10k, min=1k, max=100k, target=2000ms
func newSizer() *planner.AdaptiveChunkSizer {
	return planner.NewAdaptiveChunkSizer(10_000, 1_000, 100_000, 2_000)
}

func TestStartsAtInitialSize(t *testing.T) {
	if s := newSizer(); s.CurrentSize() != 10_000 {
		t.Errorf("CurrentSize() = %d, want 10000", s.CurrentSize())
	}
}

func TestInitialSizeClampedIntoBounds(t *testing.T) {
	low := planner.NewAdaptiveChunkSizer(10, 1_000, 100_000, 2_000)
	if low.CurrentSize() != 1_000 {
		t.Errorf("below-min initial size must be clamped to min, got %d", low.CurrentSize())
	}
	high := planner.NewAdaptiveChunkSizer(999_999, 1_000, 100_000, 2_000)
	if high.CurrentSize() != 100_000 {
		t.Errorf("above-max initial size must be clamped to max, got %d", high.CurrentSize())
	}
}

func TestRampsUpOnFastChunk(t *testing.T) {
	s := newSizer()
	// 500ms < 2000*0.5=1000 → fast → 10000*1.5=15000
	if got := s.NextSize(500); got != 15_000 {
		t.Errorf("fast chunk next size = %d, want 15000", got)
	}
}

func TestRampsDownOnSlowChunk(t *testing.T) {
	s := newSizer()
	// 5000ms > 2000*1.5=3000 → slow → 10000*0.7=7000
	if got := s.NextSize(5_000); got != 7_000 {
		t.Errorf("slow chunk next size = %d, want 7000", got)
	}
}

func TestHoldsSteadyInTargetBand(t *testing.T) {
	s := newSizer()
	if got := s.NextSize(2_000); got != 10_000 {
		t.Errorf("on-target chunk should not change size, got %d", got)
	}
	if got := s.NextSize(1_500); got != 10_000 {
		t.Errorf("within-band chunk should not change size, got %d", got)
	}
}

func TestRampUpCappedAtMax(t *testing.T) {
	s := planner.NewAdaptiveChunkSizer(90_000, 1_000, 100_000, 2_000)
	// 90000*1.5=135000 → capped to 100000
	if got := s.NextSize(100); got != 100_000 {
		t.Errorf("ramp up must cap at max, got %d", got)
	}
}

func TestRampDownFlooredAtMin(t *testing.T) {
	s := planner.NewAdaptiveChunkSizer(1_200, 1_000, 100_000, 2_000)
	// 1200*0.7=840 → floored to 1000
	if got := s.NextSize(9_999); got != 1_000 {
		t.Errorf("ramp down must floor at min, got %d", got)
	}
}

func TestRepeatedFastChunksReachMax(t *testing.T) {
	s := newSizer()
	for i := 0; i < 30; i++ {
		s.NextSize(10) // always fast
	}
	if s.CurrentSize() != 100_000 {
		t.Errorf("repeated fast chunks must reach max, got %d", s.CurrentSize())
	}
}

func TestRampDownHardHalves(t *testing.T) {
	s := newSizer()
	if got := s.RampDownHard(); got != 5_000 {
		t.Errorf("first hard ramp-down = %d, want 5000", got)
	}
	if got := s.RampDownHard(); got != 2_500 {
		t.Errorf("second hard ramp-down = %d, want 2500", got)
	}
}

func TestRampDownHardFlooredAtMin(t *testing.T) {
	s := planner.NewAdaptiveChunkSizer(1_500, 1_000, 100_000, 2_000)
	if got := s.RampDownHard(); got != 1_000 {
		t.Errorf("hard ramp-down must floor at min, got %d", got)
	}
}

func TestClonePreservesCurrentSize(t *testing.T) {
	s := newSizer()
	s.NextSize(100)
	c := s.Clone()
	if c.CurrentSize() != s.CurrentSize() {
		t.Fatalf("clone size = %d, want %d", c.CurrentSize(), s.CurrentSize())
	}
	c.NextSize(10_000)
	if s.CurrentSize() == c.CurrentSize() {
		t.Fatal("clone must be independent")
	}
}
