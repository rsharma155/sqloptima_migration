// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"path/filepath"
	"testing"

	"github.com/google/uuid"
	"github.com/ravisharma/sql-optima/engine-go/internal/core"
	"github.com/ravisharma/sql-optima/engine-go/internal/queue"
)

func openTestQueue(t *testing.T) *queue.ChunkQueue {
	t.Helper()
	dir := t.TempDir()
	q, err := queue.Open(filepath.Join(dir, "test.bbolt"))
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	t.Cleanup(func() { q.Close() })
	return q
}

func TestEnsureTableChunksEnqueuedSkipsDuplicates(t *testing.T) {
	q := openTestQueue(t)
	jobID := uuid.New()
	s, e := "0", "100"
	chunk := core.NewChunkPlan(jobID, "dbo", "orders", 0, "id", &s, &e)
	if err := ensureTableChunksEnqueued(q, jobID, "dbo", "orders", []core.ChunkPlan{chunk}); err != nil {
		t.Fatalf("first enqueue: %v", err)
	}
	if err := ensureTableChunksEnqueued(q, jobID, "dbo", "orders", []core.ChunkPlan{chunk}); err != nil {
		t.Fatalf("second enqueue: %v", err)
	}
	pending, err := q.ListChunksByStatus(jobID, core.ChunkStatusPending)
	if err != nil {
		t.Fatalf("ListChunksByStatus: %v", err)
	}
	if len(pending) != 1 {
		t.Fatalf("expected 1 pending chunk, got %d", len(pending))
	}
}

func TestPlanChunkSizePrefersTableOverride(t *testing.T) {
	m := &MigrationTableDataMover{chunkSize: 10_000}
	table := GoTableDispatchPayload{ChunkSize: 5000}
	if got := m.planChunkSize(table, nil); got != 5000 {
		t.Fatalf("planChunkSize = %d, want 5000", got)
	}
}
