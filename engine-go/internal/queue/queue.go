// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package queue

import (
	"bytes"
	"encoding/json"
	"fmt"
	"time"

	"github.com/google/uuid"
	core "github.com/ravisharma/sql-optima/engine-go/internal/core"
	bolt "go.etcd.io/bbolt"
)

// ChunkQueue is a crash-safe, bbolt-backed store for migration chunk lifecycle
// state. It replaces the Rust implementation's RocksDB dependency, eliminating
// the ~4–5 GB native-library build artefact while retaining identical semantics:
//   - All multi-bucket updates use bbolt write transactions (atomic).
//   - The file is synced on commit, so a crash cannot leave state inconsistent.
//
// ChunkQueue is goroutine-safe for concurrent reads; writes are serialised by
// bbolt's single-writer model, which is appropriate because this queue manages
// chunk *metadata* only (not bulk row data).
type ChunkQueue struct {
	db *bolt.DB
}

// Open opens (or creates) a ChunkQueue at path and ensures all four buckets
// exist.
func Open(path string) (*ChunkQueue, error) {
	db, err := bolt.Open(path, 0600, &bolt.Options{Timeout: 5 * time.Second})
	if err != nil {
		return nil, &core.QueueError{Msg: fmt.Sprintf("open %s: %v", path, err)}
	}
	if err := db.Update(func(tx *bolt.Tx) error {
		for _, name := range allBuckets {
			if _, err := tx.CreateBucketIfNotExists(name); err != nil {
				return err
			}
		}
		return nil
	}); err != nil {
		return nil, &core.QueueError{Msg: fmt.Sprintf("init buckets: %v", err)}
	}
	return &ChunkQueue{db: db}, nil
}

// Close releases the bbolt file handle.
func (q *ChunkQueue) Close() error { return q.db.Close() }

// ---------------------------------------------------------------------------
// Chunk CRUD
// ---------------------------------------------------------------------------

// Enqueue persists a new PENDING chunk atomically: it writes the JSON to the
// chunks bucket and adds an index entry in status_idx in a single transaction.
func (q *ChunkQueue) Enqueue(chunk *core.ChunkPlan) error {
	data, err := json.Marshal(chunk)
	if err != nil {
		return &core.QueueError{Msg: fmt.Sprintf("marshal chunk: %v", err)}
	}
	return q.db.Update(func(tx *bolt.Tx) error {
		if err := tx.Bucket(bucketChunks).Put(
			chunkKey(chunk.JobID, chunk.ID), data); err != nil {
			return err
		}
		return tx.Bucket(bucketStatusIdx).Put(
			statusKey(chunk.JobID, chunk.Status, chunk.ID), []byte{})
	})
}

// GetChunk retrieves a chunk by its job + chunk IDs.
// Returns (nil, nil) when the chunk does not exist.
func (q *ChunkQueue) GetChunk(jobID, chunkID uuid.UUID) (*core.ChunkPlan, error) {
	var plan *core.ChunkPlan
	err := q.db.View(func(tx *bolt.Tx) error {
		data := tx.Bucket(bucketChunks).Get(chunkKey(jobID, chunkID))
		if data == nil {
			return nil
		}
		plan = new(core.ChunkPlan)
		return json.Unmarshal(data, plan)
	})
	if err != nil {
		return nil, &core.QueueError{Msg: err.Error()}
	}
	return plan, nil
}

// UpdateStatus atomically transitions chunk to newStatus:
// removes the old status_idx entry, updates the JSON, inserts a new index entry.
func (q *ChunkQueue) UpdateStatus(
	jobID, chunkID uuid.UUID,
	oldStatus, newStatus core.ChunkStatus,
) (*core.ChunkPlan, error) {

	var updated *core.ChunkPlan
	err := q.db.Update(func(tx *bolt.Tx) error {
		chunks := tx.Bucket(bucketChunks)
		idx := tx.Bucket(bucketStatusIdx)

		data := chunks.Get(chunkKey(jobID, chunkID))
		if data == nil {
			return &core.ChunkNotFoundError{ID: chunkID}
		}
		var plan core.ChunkPlan
		if err := json.Unmarshal(data, &plan); err != nil {
			return err
		}

		// Swap status index entries atomically within the same transaction.
		if err := idx.Delete(statusKey(jobID, oldStatus, chunkID)); err != nil {
			return err
		}
		plan.Status = newStatus
		newData, err := json.Marshal(&plan)
		if err != nil {
			return err
		}
		if err := chunks.Put(chunkKey(jobID, chunkID), newData); err != nil {
			return err
		}
		if err := idx.Put(statusKey(jobID, newStatus, chunkID), []byte{}); err != nil {
			return err
		}
		updated = &plan
		return nil
	})
	if err != nil {
		return nil, err
	}
	return updated, nil
}

// ClaimChunk atomically transitions a PENDING chunk to CLAIMED, recording the
// worker ID and claim timestamp. Returns an error if the chunk is not PENDING.
func (q *ChunkQueue) ClaimChunk(jobID, chunkID uuid.UUID, workerID string) (*core.ChunkPlan, error) {
	var claimed *core.ChunkPlan
	err := q.db.Update(func(tx *bolt.Tx) error {
		chunks := tx.Bucket(bucketChunks)
		idx := tx.Bucket(bucketStatusIdx)

		data := chunks.Get(chunkKey(jobID, chunkID))
		if data == nil {
			return &core.ChunkNotFoundError{ID: chunkID}
		}
		var plan core.ChunkPlan
		if err := json.Unmarshal(data, &plan); err != nil {
			return err
		}
		if plan.Status != core.ChunkStatusPending {
			return &core.StateTransitionError{
				Msg: fmt.Sprintf("cannot claim chunk %s in status %s", chunkID, plan.Status),
			}
		}

		now := time.Now().UTC()
		if err := idx.Delete(statusKey(jobID, core.ChunkStatusPending, chunkID)); err != nil {
			return err
		}
		plan.Status = core.ChunkStatusClaimed
		plan.ClaimedBy = &workerID
		plan.ClaimedAt = &now
		newData, err := json.Marshal(&plan)
		if err != nil {
			return err
		}
		if err := chunks.Put(chunkKey(jobID, chunkID), newData); err != nil {
			return err
		}
		if err := idx.Put(statusKey(jobID, core.ChunkStatusClaimed, chunkID), []byte{}); err != nil {
			return err
		}
		claimed = &plan
		return nil
	})
	if err != nil {
		return nil, err
	}
	return claimed, nil
}

// ClaimNextPending atomically claims the first PENDING chunk for a job.
// Returns (nil, nil) when no pending chunk exists.
func (q *ChunkQueue) ClaimNextPending(jobID uuid.UUID, workerID string) (*core.ChunkPlan, error) {
	var claimed *core.ChunkPlan
	err := q.db.Update(func(tx *bolt.Tx) error {
		idx := tx.Bucket(bucketStatusIdx)
		chunks := tx.Bucket(bucketChunks)
		prefix := statusPrefix(jobID, core.ChunkStatusPending)
		k, _ := idx.Cursor().Seek(prefix)
		if k == nil || !bytes.HasPrefix(k, prefix) {
			return nil
		}
		chunkID, err := parseChunkIDFromStatusKey(k)
		if err != nil {
			return err
		}
		data := chunks.Get(chunkKey(jobID, chunkID))
		if data == nil {
			return &core.ChunkNotFoundError{ID: chunkID}
		}
		var plan core.ChunkPlan
		if err := json.Unmarshal(data, &plan); err != nil {
			return err
		}
		if plan.Status != core.ChunkStatusPending {
			return nil
		}
		now := time.Now().UTC()
		if err := idx.Delete(statusKey(jobID, core.ChunkStatusPending, chunkID)); err != nil {
			return err
		}
		plan.Status = core.ChunkStatusClaimed
		plan.ClaimedBy = &workerID
		plan.ClaimedAt = &now
		newData, err := json.Marshal(&plan)
		if err != nil {
			return err
		}
		if err := chunks.Put(chunkKey(jobID, chunkID), newData); err != nil {
			return err
		}
		if err := idx.Put(statusKey(jobID, core.ChunkStatusClaimed, chunkID), []byte{}); err != nil {
			return err
		}
		claimed = &plan
		return nil
	})
	if err != nil {
		return nil, err
	}
	return claimed, nil
}

// PeekNextPending returns the ID of the first PENDING chunk for a job without
// claiming it. Returns (nil, nil) when no pending chunk exists.
func (q *ChunkQueue) PeekNextPending(jobID uuid.UUID) (*uuid.UUID, error) {
	prefix := statusPrefix(jobID, core.ChunkStatusPending)
	var found *uuid.UUID

	err := q.db.View(func(tx *bolt.Tx) error {
		c := tx.Bucket(bucketStatusIdx).Cursor()
		k, _ := c.Seek(prefix)
		if k == nil || !bytes.HasPrefix(k, prefix) {
			return nil
		}
		id, err := parseChunkIDFromStatusKey(k)
		if err != nil {
			return err
		}
		found = &id
		return nil
	})
	if err != nil {
		return nil, &core.QueueError{Msg: err.Error()}
	}
	return found, nil
}

// ListChunksByStatus returns all chunks for a job in the given status.
func (q *ChunkQueue) ListChunksByStatus(jobID uuid.UUID, status core.ChunkStatus) ([]core.ChunkPlan, error) {
	prefix := statusPrefix(jobID, status)
	var plans []core.ChunkPlan

	err := q.db.View(func(tx *bolt.Tx) error {
		idxCursor := tx.Bucket(bucketStatusIdx).Cursor()
		chunksBucket := tx.Bucket(bucketChunks)

		for k, _ := idxCursor.Seek(prefix); k != nil && bytes.HasPrefix(k, prefix); k, _ = idxCursor.Next() {
			id, err := parseChunkIDFromStatusKey(k)
			if err != nil {
				continue
			}
			data := chunksBucket.Get(chunkKey(jobID, id))
			if data == nil {
				continue
			}
			var plan core.ChunkPlan
			if err := json.Unmarshal(data, &plan); err != nil {
				return err
			}
			plans = append(plans, plan)
		}
		return nil
	})
	if err != nil {
		return nil, &core.QueueError{Msg: err.Error()}
	}
	return plans, nil
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

// SetCommand writes (or overwrites) the pending command for a job.
func (q *ChunkQueue) SetCommand(jobID uuid.UUID, cmd core.Command) error {
	return q.db.Update(func(tx *bolt.Tx) error {
		return tx.Bucket(bucketCommands).Put(commandKey(jobID), []byte(cmd))
	})
}

// GetCommand reads the current command for a job.
// Returns ("", false, nil) when no command is pending.
func (q *ChunkQueue) GetCommand(jobID uuid.UUID) (core.Command, bool, error) {
	var cmd core.Command
	var found bool
	err := q.db.View(func(tx *bolt.Tx) error {
		data := tx.Bucket(bucketCommands).Get(commandKey(jobID))
		if data == nil {
			return nil
		}
		cmd, found = core.Command(data), true
		return nil
	})
	if err != nil {
		return "", false, &core.QueueError{Msg: err.Error()}
	}
	return cmd, found, nil
}

// ClearCommand removes the command once the engine has acted on it.
func (q *ChunkQueue) ClearCommand(jobID uuid.UUID) error {
	return q.db.Update(func(tx *bolt.Tx) error {
		return tx.Bucket(bucketCommands).Delete(commandKey(jobID))
	})
}

// ---------------------------------------------------------------------------
// Checkpoints
// ---------------------------------------------------------------------------

// SetCheckpoint persists the last successfully loaded chunk ID for a (job, table) pair.
func (q *ChunkQueue) SetCheckpoint(jobID uuid.UUID, tableQualified string, lastChunkID uuid.UUID) error {
	return q.db.Update(func(tx *bolt.Tx) error {
		return tx.Bucket(bucketCheckpoints).Put(
			checkpointKey(jobID, tableQualified),
			[]byte(lastChunkID.String()),
		)
	})
}

// GetCheckpoint retrieves the last checkpoint chunk ID for a (job, table) pair.
// Returns (nil, nil) when no checkpoint has been saved yet.
func (q *ChunkQueue) GetCheckpoint(jobID uuid.UUID, tableQualified string) (*uuid.UUID, error) {
	var found *uuid.UUID
	err := q.db.View(func(tx *bolt.Tx) error {
		data := tx.Bucket(bucketCheckpoints).Get(checkpointKey(jobID, tableQualified))
		if data == nil {
			return nil
		}
		id, err := uuid.Parse(string(data))
		if err != nil {
			return err
		}
		found = &id
		return nil
	})
	if err != nil {
		return nil, &core.QueueError{Msg: err.Error()}
	}
	return found, nil
}
