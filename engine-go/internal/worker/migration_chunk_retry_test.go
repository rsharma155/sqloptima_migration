// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"errors"
	"fmt"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
)

func TestChunkRetryDelaysMatchPython(t *testing.T) {
	want := []time.Duration{0, 30 * time.Second, 120 * time.Second}
	if len(ChunkRetryDelays) != len(want) {
		t.Fatalf("delays len = %d, want %d", len(ChunkRetryDelays), len(want))
	}
	for i := range want {
		if ChunkRetryDelays[i] != want[i] {
			t.Fatalf("delay[%d] = %v, want %v", i, ChunkRetryDelays[i], want[i])
		}
	}
}

func TestRunChunkWithRetrySucceedsOnSecondAttempt(t *testing.T) {
	old := ChunkRetryDelays
	ChunkRetryDelays = []time.Duration{0, time.Millisecond, time.Millisecond}
	defer func() { ChunkRetryDelays = old }()

	jobID := uuid.New()
	chunk := core.NewChunkPlan(jobID, "dbo", "t", 0, "id", strPtr("1"), strPtr("2"))
	attempts := 0
	rows, err := runChunkWithRetry(t.Context(), chunk, func() (int64, error) {
		attempts++
		if attempts < 2 {
			return 0, fmt.Errorf("transient")
		}
		return 5, nil
	})
	if err != nil || rows != 5 || attempts != 2 {
		t.Fatalf("rows=%d err=%v attempts=%d", rows, err, attempts)
	}
}

func TestRunChunkWithRetryQuarantinesAfterMaxAttempts(t *testing.T) {
	old := ChunkRetryDelays
	ChunkRetryDelays = []time.Duration{0, time.Millisecond, time.Millisecond}
	defer func() { ChunkRetryDelays = old }()

	jobID := uuid.New()
	chunk := core.NewChunkPlan(jobID, "dbo", "t", 1, "id", strPtr("3"), strPtr("4"))
	attempts := 0
	_, err := runChunkWithRetry(t.Context(), chunk, func() (int64, error) {
		attempts++
		return 0, fmt.Errorf("permanent")
	})
	if attempts != maxChunkAttempts {
		t.Fatalf("attempts = %d, want %d", attempts, maxChunkAttempts)
	}
	var q ErrChunkQuarantined
	if !errors.As(err, &q) {
		t.Fatalf("expected ErrChunkQuarantined, got %v", err)
	}
	if q.Chunk.ChunkIndex != 1 {
		t.Fatalf("chunk index = %d", q.Chunk.ChunkIndex)
	}
}
