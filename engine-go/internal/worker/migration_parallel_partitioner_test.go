// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"testing"

	"github.com/google/uuid"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
)

func TestPartitionChunks_evenSplit(t *testing.T) {
	jobID := uuid.New()
	chunks := make([]core.ChunkPlan, 8)
	for i := range chunks {
		chunks[i] = core.NewChunkPlan(jobID, "dbo", "t", uint32(i), "id", strPtr("1"), strPtr("2"))
	}
	parts := PartitionChunks(chunks, 4)
	if len(parts) != 4 {
		t.Fatalf("expected 4 partitions, got %d", len(parts))
	}
	for i, p := range parts {
		if len(p) != 2 {
			t.Fatalf("partition %d: expected 2 chunks, got %d", i, len(p))
		}
	}
}

func TestPartitionChunks_singleWorker(t *testing.T) {
	jobID := uuid.New()
	chunks := []core.ChunkPlan{
		core.NewChunkPlan(jobID, "dbo", "t", 0, "id", strPtr("1"), strPtr("2")),
	}
	parts := PartitionChunks(chunks, 1)
	if len(parts) != 1 || len(parts[0]) != 1 {
		t.Fatalf("unexpected partitions: %+v", parts)
	}
}

func TestPartitionChunks_moreWorkersThanChunks(t *testing.T) {
	jobID := uuid.New()
	chunks := []core.ChunkPlan{
		core.NewChunkPlan(jobID, "dbo", "t", 0, "id", strPtr("1"), strPtr("2")),
		core.NewChunkPlan(jobID, "dbo", "t", 1, "id", strPtr("3"), strPtr("4")),
	}
	parts := PartitionChunks(chunks, 8)
	if len(parts) != 2 {
		t.Fatalf("expected 2 partitions (1 chunk each), got %d", len(parts))
	}
}

func TestEffectiveParallelWorkers(t *testing.T) {
	if effectiveParallelWorkers(0) != 1 {
		t.Fatal("zero should become 1")
	}
	if effectiveParallelWorkers(100) != maxParallelWorkers {
		t.Fatal("should cap at max")
	}
}

func TestIsParallelChunkedStrategy(t *testing.T) {
	if !isParallelChunkedStrategy("parallel_chunked") {
		t.Fatal("expected parallel_chunked")
	}
	if isParallelChunkedStrategy("chunked") {
		t.Fatal("chunked is sequential")
	}
}

func strPtr(s string) *string { return &s }
