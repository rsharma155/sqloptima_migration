// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"context"
	"time"
)

// SourceThrottleConfig controls pauses between consecutive source chunk reads.
type SourceThrottleConfig struct {
	Enabled                    bool    `json:"enabled"`
	SmallTableDelaySec         float64 `json:"small_table_delay_sec"`
	LargeTableDelaySec         float64 `json:"large_table_delay_sec"`
	LargeTableRowThreshold     int64   `json:"large_table_row_threshold"`
	LargeTableSizeMBThreshold  float64 `json:"large_table_size_mb_threshold"`
}

func defaultSourceThrottleConfig() SourceThrottleConfig {
	return SourceThrottleConfig{
		Enabled:                   true,
		SmallTableDelaySec:        1.0,
		LargeTableDelaySec:        4.0,
		LargeTableRowThreshold:    100_000,
		LargeTableSizeMBThreshold: 50.0,
	}
}

func (c SourceThrottleConfig) withDefaults() SourceThrottleConfig {
	d := defaultSourceThrottleConfig()
	if c.SmallTableDelaySec <= 0 {
		c.SmallTableDelaySec = d.SmallTableDelaySec
	}
	if c.LargeTableDelaySec <= 0 {
		c.LargeTableDelaySec = d.LargeTableDelaySec
	}
	if c.LargeTableRowThreshold <= 0 {
		c.LargeTableRowThreshold = d.LargeTableRowThreshold
	}
	if c.LargeTableSizeMBThreshold <= 0 {
		c.LargeTableSizeMBThreshold = d.LargeTableSizeMBThreshold
	}
	return c
}

func isLargeSourceTable(table GoTableDispatchPayload, cfg SourceThrottleConfig) bool {
	if table.RowCountEstimate >= cfg.LargeTableRowThreshold {
		return true
	}
	if table.TableSizeMB >= cfg.LargeTableSizeMBThreshold {
		return true
	}
	return false
}

func resolveChunkDelay(table GoTableDispatchPayload, cfg SourceThrottleConfig) time.Duration {
	cfg = cfg.withDefaults()
	if !cfg.Enabled {
		return 0
	}
	delaySec := cfg.SmallTableDelaySec
	if isLargeSourceTable(table, cfg) {
		delaySec = cfg.LargeTableDelaySec
	}
	if table.ChunkDelaySec > 0 {
		delaySec = table.ChunkDelaySec
	}
	return time.Duration(delaySec * float64(time.Second))
}

func sleepBetweenSourceChunks(ctx context.Context, delay time.Duration) error {
	if delay <= 0 {
		return nil
	}
	timer := time.NewTimer(delay)
	defer timer.Stop()
	select {
	case <-timer.C:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}
