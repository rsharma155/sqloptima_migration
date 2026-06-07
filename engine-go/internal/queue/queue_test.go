// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package queue_test

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/google/uuid"
	"github.com/ravisharma/sql-optima/engine-go/internal/core"
	"github.com/ravisharma/sql-optima/engine-go/internal/queue"
)

// openTmp opens a queue in a temporary directory and registers cleanup.
func openTmp(t *testing.T) *queue.ChunkQueue {
	t.Helper()
	dir := t.TempDir()
	q, err := queue.Open(filepath.Join(dir, "test.bbolt"))
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	t.Cleanup(func() { q.Close() })
	return q
}

func makeChunk(jobID uuid.UUID) *core.ChunkPlan {
	s, e := "0", "1000"
	c := core.NewChunkPlan(jobID, "dbo", "orders", 0, "id", &s, &e)
	return &c
}

// ---------------------------------------------------------------------------
// Enqueue / GetChunk
// ---------------------------------------------------------------------------

func TestEnqueueAndRetrieve(t *testing.T) {
	q := openTmp(t)
	jobID := uuid.New()
	chunk := makeChunk(jobID)
	if err := q.Enqueue(chunk); err != nil {
		t.Fatalf("Enqueue: %v", err)
	}
	got, err := q.GetChunk(jobID, chunk.ID)
	if err != nil || got == nil {
		t.Fatalf("GetChunk: got=%v err=%v", got, err)
	}
	if got.ID != chunk.ID {
		t.Errorf("ID mismatch: got %s, want %s", got.ID, chunk.ID)
	}
	if got.Status != core.ChunkStatusPending {
		t.Errorf("status = %s, want PENDING", got.Status)
	}
}

func TestGetMissingChunkReturnsNil(t *testing.T) {
	q := openTmp(t)
	got, err := q.GetChunk(uuid.New(), uuid.New())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != nil {
		t.Error("missing chunk must return nil")
	}
}

// ---------------------------------------------------------------------------
// UpdateStatus
// ---------------------------------------------------------------------------

func TestUpdateStatusTransitionsCorrectly(t *testing.T) {
	q := openTmp(t)
	jobID := uuid.New()
	chunk := makeChunk(jobID)
	q.Enqueue(chunk) //nolint:errcheck

	updated, err := q.UpdateStatus(jobID, chunk.ID, core.ChunkStatusPending, core.ChunkStatusClaimed)
	if err != nil {
		t.Fatalf("UpdateStatus: %v", err)
	}
	if updated.Status != core.ChunkStatusClaimed {
		t.Errorf("updated status = %s, want CLAIMED", updated.Status)
	}

	fetched, _ := q.GetChunk(jobID, chunk.ID)
	if fetched.Status != core.ChunkStatusClaimed {
		t.Errorf("persisted status = %s, want CLAIMED", fetched.Status)
	}
}

// ---------------------------------------------------------------------------
// ClaimChunk
// ---------------------------------------------------------------------------

func TestClaimChunkMarksPendingAsClaimed(t *testing.T) {
	q := openTmp(t)
	jobID := uuid.New()
	chunk := makeChunk(jobID)
	q.Enqueue(chunk) //nolint:errcheck

	claimed, err := q.ClaimChunk(jobID, chunk.ID, "worker-1")
	if err != nil {
		t.Fatalf("ClaimChunk: %v", err)
	}
	if claimed.Status != core.ChunkStatusClaimed {
		t.Errorf("claimed status = %s, want CLAIMED", claimed.Status)
	}
	if claimed.ClaimedBy == nil || *claimed.ClaimedBy != "worker-1" {
		t.Error("claimed_by must be worker-1")
	}
	if claimed.ClaimedAt == nil {
		t.Error("claimed_at must be set")
	}
}

func TestClaimAlreadyClaimedChunkErrors(t *testing.T) {
	q := openTmp(t)
	jobID := uuid.New()
	chunk := makeChunk(jobID)
	q.Enqueue(chunk)                    //nolint:errcheck
	q.ClaimChunk(jobID, chunk.ID, "w1") //nolint:errcheck

	if _, err := q.ClaimChunk(jobID, chunk.ID, "w2"); err == nil {
		t.Error("claiming an already-claimed chunk must return error")
	}
}

func TestClaimNextPendingAtomicallyClaimsFirst(t *testing.T) {
	q := openTmp(t)
	jobID := uuid.New()
	c1 := makeChunk(jobID)
	c2 := makeChunk(jobID)
	c2.ChunkIndex = 1
	q.Enqueue(c1) //nolint:errcheck
	q.Enqueue(c2) //nolint:errcheck

	claimed, err := q.ClaimNextPending(jobID, "worker-a")
	if err != nil || claimed == nil {
		t.Fatalf("ClaimNextPending: %v", err)
	}
	if claimed.ID != c1.ID {
		t.Fatalf("claimed %s, want %s", claimed.ID, c1.ID)
	}
	if claimed.Status != core.ChunkStatusClaimed {
		t.Errorf("status = %s, want CLAIMED", claimed.Status)
	}

	id, err := q.PeekNextPending(jobID)
	if err != nil || id == nil || *id != c2.ID {
		t.Fatalf("next pending = %v err=%v, want %s", id, err, c2.ID)
	}
}

// ---------------------------------------------------------------------------
// PeekNextPending
// ---------------------------------------------------------------------------

func TestPeekNextPendingReturnsPendingChunk(t *testing.T) {
	q := openTmp(t)
	jobID := uuid.New()
	chunk := makeChunk(jobID)
	q.Enqueue(chunk) //nolint:errcheck

	id, err := q.PeekNextPending(jobID)
	if err != nil || id == nil {
		t.Fatalf("PeekNextPending: id=%v err=%v", id, err)
	}
	if *id != chunk.ID {
		t.Errorf("peeked chunk ID mismatch")
	}
}

func TestPeekNextPendingEmptyReturnsNil(t *testing.T) {
	q := openTmp(t)
	id, err := q.PeekNextPending(uuid.New())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if id != nil {
		t.Error("no pending chunks must return nil")
	}
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

func TestSetAndGetCommand(t *testing.T) {
	q := openTmp(t)
	jobID := uuid.New()
	if err := q.SetCommand(jobID, core.CommandPause); err != nil {
		t.Fatalf("SetCommand: %v", err)
	}
	cmd, found, err := q.GetCommand(jobID)
	if err != nil || !found {
		t.Fatalf("GetCommand: cmd=%v found=%v err=%v", cmd, found, err)
	}
	if cmd != core.CommandPause {
		t.Errorf("cmd = %s, want PAUSE", cmd)
	}
}

func TestGetCommandReturnsNotFoundWhenAbsent(t *testing.T) {
	q := openTmp(t)
	_, found, err := q.GetCommand(uuid.New())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if found {
		t.Error("absent command must return found=false")
	}
}

func TestCommandDetectsPause(t *testing.T) {
	q := openTmp(t)
	jobID := uuid.New()
	q.SetCommand(jobID, core.CommandPause) //nolint:errcheck
	cmd, _, _ := q.GetCommand(jobID)
	if !cmd.IsPause() {
		t.Error("PAUSE command must be detected as pause")
	}
}

func TestCommandDetectsStop(t *testing.T) {
	q := openTmp(t)
	jobID := uuid.New()
	q.SetCommand(jobID, core.CommandStop) //nolint:errcheck
	cmd, _, _ := q.GetCommand(jobID)
	if !cmd.IsStop() {
		t.Error("STOP command must be detected as stop")
	}
}

func TestClearCommandRemovesIt(t *testing.T) {
	q := openTmp(t)
	jobID := uuid.New()
	q.SetCommand(jobID, core.CommandResume) //nolint:errcheck
	q.ClearCommand(jobID)                  //nolint:errcheck
	_, found, _ := q.GetCommand(jobID)
	if found {
		t.Error("cleared command must not be found")
	}
}

func TestOverwriteCommandReplacesPrevious(t *testing.T) {
	q := openTmp(t)
	jobID := uuid.New()
	q.SetCommand(jobID, core.CommandPause) //nolint:errcheck
	q.SetCommand(jobID, core.CommandStop)  //nolint:errcheck
	cmd, _, _ := q.GetCommand(jobID)
	if cmd != core.CommandStop {
		t.Errorf("overwritten command = %s, want STOP", cmd)
	}
}

// ---------------------------------------------------------------------------
// Checkpoints
// ---------------------------------------------------------------------------

func TestSetAndGetCheckpoint(t *testing.T) {
	q := openTmp(t)
	jobID := uuid.New()
	chunkID := uuid.New()
	q.SetCheckpoint(jobID, "dbo.orders", chunkID) //nolint:errcheck

	got, err := q.GetCheckpoint(jobID, "dbo.orders")
	if err != nil || got == nil {
		t.Fatalf("GetCheckpoint: got=%v err=%v", got, err)
	}
	if *got != chunkID {
		t.Errorf("checkpoint ID mismatch")
	}
}

func TestGetCheckpointMissingReturnsNil(t *testing.T) {
	q := openTmp(t)
	got, err := q.GetCheckpoint(uuid.New(), "dbo.missing")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != nil {
		t.Error("missing checkpoint must return nil")
	}
}

// ---------------------------------------------------------------------------
// Crash-recovery
// ---------------------------------------------------------------------------

func TestQueueSurvivesCrashAndReload(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "crash.bbolt")
	jobID := uuid.New()
	var chunkID uuid.UUID

	// Phase 1: open, enqueue, close (simulates crash / clean shutdown).
	{
		q, err := queue.Open(path)
		if err != nil {
			t.Fatalf("open phase 1: %v", err)
		}
		chunk := makeChunk(jobID)
		chunkID = chunk.ID
		q.Enqueue(chunk) //nolint:errcheck
		q.Close()
	}

	// Phase 2: reopen and verify data survived.
	{
		q, err := queue.Open(path)
		if err != nil {
			t.Fatalf("open phase 2: %v", err)
		}
		defer q.Close()
		recovered, err := q.GetChunk(jobID, chunkID)
		if err != nil {
			t.Fatalf("GetChunk after reload: %v", err)
		}
		if recovered == nil {
			t.Fatal("chunk must survive simulated crash")
		}
		if recovered.Status != core.ChunkStatusPending {
			t.Errorf("recovered status = %s, want PENDING", recovered.Status)
		}
	}
}

func TestMultipleChunksSurviveCrash(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "multi.bbolt")
	jobID := uuid.New()
	var ids []uuid.UUID

	{
		q, _ := queue.Open(path)
		for i := 0; i < 5; i++ {
			s := "0"
			e := "100"
			c := core.NewChunkPlan(jobID, "dbo", "orders", uint32(i), "id", &s, &e)
			ids = append(ids, c.ID)
			q.Enqueue(&c) //nolint:errcheck
		}
		q.Close()
	}

	{
		q, _ := queue.Open(path)
		defer q.Close()
		for _, id := range ids {
			c, err := q.GetChunk(jobID, id)
			if err != nil || c == nil {
				t.Errorf("chunk %s must survive crash", id)
			}
		}
	}
}

// ---------------------------------------------------------------------------
// ListChunksByStatus
// ---------------------------------------------------------------------------

func TestListChunksByStatusReturnsPendingChunks(t *testing.T) {
	q := openTmp(t)
	jobID := uuid.New()

	// Enqueue 3 chunks.
	chunks := make([]*core.ChunkPlan, 3)
	for i := range chunks {
		c := makeChunk(jobID)
		if err := q.Enqueue(c); err != nil {
			t.Fatalf("Enqueue: %v", err)
		}
		chunks[i] = c
	}

	// Claim the first one (moves it out of PENDING).
	q.ClaimChunk(jobID, chunks[0].ID, "w1") //nolint:errcheck

	pending, err := q.ListChunksByStatus(jobID, core.ChunkStatusPending)
	if err != nil {
		t.Fatalf("ListChunksByStatus: %v", err)
	}
	if len(pending) != 2 {
		t.Errorf("expected 2 PENDING chunks, got %d", len(pending))
	}

	claimed, err := q.ListChunksByStatus(jobID, core.ChunkStatusClaimed)
	if err != nil {
		t.Fatalf("ListChunksByStatus claimed: %v", err)
	}
	if len(claimed) != 1 {
		t.Errorf("expected 1 CLAIMED chunk, got %d", len(claimed))
	}
}

func TestListChunksByStatusEmptyReturnsNil(t *testing.T) {
	q := openTmp(t)
	chunks, err := q.ListChunksByStatus(uuid.New(), core.ChunkStatusLoaded)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(chunks) != 0 {
		t.Errorf("expected 0 chunks, got %d", len(chunks))
	}
}

// ---------------------------------------------------------------------------
// Error wrapping
// ---------------------------------------------------------------------------

func TestChunkNotFoundErrorWrapssentinel(t *testing.T) {
	err := &core.ChunkNotFoundError{ID: uuid.New()}
	if !errors.Is(err, core.ErrChunkNotFound) {
		t.Error("ChunkNotFoundError must wrap ErrChunkNotFound")
	}
}

func TestQueueFileIsCreatedOnOpen(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "new.bbolt")
	q, err := queue.Open(path)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	q.Close()
	if _, err := os.Stat(path); os.IsNotExist(err) {
		t.Error("bbolt file must exist after Open")
	}
}
