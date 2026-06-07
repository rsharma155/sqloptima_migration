// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"context"
	"fmt"
	"time"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
)

// ChunkRetryDelays mirrors Python RETRY_DELAYS_SEC = [0, 30, 120].
var ChunkRetryDelays = []time.Duration{
	0,
	30 * time.Second,
	120 * time.Second,
}

const maxChunkAttempts = 3

// ErrChunkQuarantined is returned when a chunk exhausts all retry attempts.
type ErrChunkQuarantined struct {
	Chunk core.ChunkPlan
	Cause error
}

func (e ErrChunkQuarantined) Error() string {
	return fmt.Sprintf("chunk %d quarantined after %d attempts: %v",
		e.Chunk.ChunkIndex, maxChunkAttempts, e.Cause)
}

func (e ErrChunkQuarantined) Unwrap() error { return e.Cause }

// runChunkWithRetry executes fn up to maxChunkAttempts times with backoff between failures.
func runChunkWithRetry(ctx context.Context, chunk core.ChunkPlan, fn func() (int64, error)) (int64, error) {
	var lastErr error
	for attempt := 0; attempt < maxChunkAttempts; attempt++ {
		if attempt > 0 {
			idx := attempt - 1
			if idx >= len(ChunkRetryDelays) {
				idx = len(ChunkRetryDelays) - 1
			}
			delay := ChunkRetryDelays[idx]
			if delay > 0 {
				timer := time.NewTimer(delay)
				select {
				case <-timer.C:
				case <-ctx.Done():
					timer.Stop()
					return 0, ctx.Err()
				}
			}
		}
		rows, err := fn()
		if err == nil {
			return rows, nil
		}
		lastErr = err
	}
	return 0, ErrChunkQuarantined{Chunk: chunk, Cause: lastErr}
}
