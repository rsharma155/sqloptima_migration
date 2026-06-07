// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package planner

// Adaptive chunk-size feedback constants (§9.3 of the architecture plan).
const (
	rampUpFactor   = 1.5 // multiply size on fast chunk
	rampDownFactor = 0.7 // multiply size on slow chunk
	fastThreshold  = 0.5 // chunk is "fast" when duration < target × this
	slowThreshold  = 1.5 // chunk is "slow" when duration > target × this
)

// AdaptiveChunkSizer adjusts the chunk size between chunks based on the
// observed extraction latency of the previous chunk.
//
// Algorithm:
//
//	IF   duration < target × 0.5  → ramp up   (size × 1.5, capped at max)
//	ELIF duration > target × 1.5  → ramp down (size × 0.7, floored at min)
//	ELSE                          → keep unchanged
//
// The sizer is NOT goroutine-safe; each extractor worker owns its own copy.
type AdaptiveChunkSizer struct {
	current  int64
	min, max int64
	targetMs int64
}

// NewAdaptiveChunkSizer creates a sizer. initial is clamped into [min, max].
func NewAdaptiveChunkSizer(initial, min, max, targetMs int64) *AdaptiveChunkSizer {
	if min > max {
		min, max = max, min // guard against inverted bounds
	}
	if initial < min {
		initial = min
	}
	if initial > max {
		initial = max
	}
	return &AdaptiveChunkSizer{current: initial, min: min, max: max, targetMs: targetMs}
}

// CurrentSize returns the size that will be used for the next chunk.
func (s *AdaptiveChunkSizer) CurrentSize() int64 { return s.current }

// NextSize feeds the duration of the chunk that just finished and returns
// the size to use for the next chunk, mutating internal state.
func (s *AdaptiveChunkSizer) NextSize(lastDurationMs int64) int64 {
	target := float64(s.targetMs)
	observed := float64(lastDurationMs)

	var next float64
	switch {
	case observed < target*fastThreshold:
		next = float64(s.current) * rampUpFactor
	case observed > target*slowThreshold:
		next = float64(s.current) * rampDownFactor
	default:
		next = float64(s.current)
	}

	// Round to nearest to avoid systematic truncation drift.
	rounded := int64(next + 0.5)
	s.current = clamp(rounded, s.min, s.max)
	return s.current
}

// Clone returns a copy with the same tuning bounds and current size.
func (s *AdaptiveChunkSizer) Clone() *AdaptiveChunkSizer {
	if s == nil {
		return nil
	}
	return &AdaptiveChunkSizer{
		current:  s.current,
		min:      s.min,
		max:      s.max,
		targetMs: s.targetMs,
	}
}

// RampDownHard immediately halves the current size (used on detected memory
// pressure). Floored at min.
func (s *AdaptiveChunkSizer) RampDownHard() int64 {
	s.current = clamp(s.current/2, s.min, s.max)
	return s.current
}

func clamp(v, lo, hi int64) int64 {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}
