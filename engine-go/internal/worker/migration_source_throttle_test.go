// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import "testing"

func TestResolveChunkDelayLargeTableByRows(t *testing.T) {
	cfg := SourceThrottleConfig{
		Enabled:                true,
		SmallTableDelaySec:     1.0,
		LargeTableDelaySec:     4.0,
		LargeTableRowThreshold: 100_000,
		LargeTableSizeMBThreshold: 50.0,
	}
	table := GoTableDispatchPayload{RowCountEstimate: 1_000_000}
	delay := resolveChunkDelay(table, cfg)
	if delay.Seconds() != 4.0 {
		t.Fatalf("delay = %v want 4s for large table", delay)
	}
}

func TestResolveChunkDelaySmallTable(t *testing.T) {
	cfg := defaultSourceThrottleConfig()
	table := GoTableDispatchPayload{RowCountEstimate: 10_000, TableSizeMB: 5}
	delay := resolveChunkDelay(table, cfg)
	if delay.Seconds() != 1.0 {
		t.Fatalf("delay = %v want 1s for small table", delay)
	}
}

func TestResolveChunkDelayPerTableOverride(t *testing.T) {
	cfg := defaultSourceThrottleConfig()
	table := GoTableDispatchPayload{RowCountEstimate: 1_000_000, ChunkDelaySec: 2.5}
	delay := resolveChunkDelay(table, cfg)
	if delay.Seconds() != 2.5 {
		t.Fatalf("delay = %v want per-table override 2.5s", delay)
	}
}
