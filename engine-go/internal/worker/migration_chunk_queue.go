// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"fmt"

	"github.com/google/uuid"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
	"github.com/ravisharma/sql-optima/engine-go/internal/queue"
)

func tableCheckpointKey(schema, table string) string {
	return fmt.Sprintf("%s.%s", schema, table)
}

func chunkMatchesTable(chunk core.ChunkPlan, schema, table string) bool {
	return chunk.TableSchema == schema && chunk.TableName == table
}

// hasQueuedTableChunks reports whether any chunks for schema.table already exist in the queue.
func hasQueuedTableChunks(q *queue.ChunkQueue, jobID uuid.UUID, schema, table string) (bool, error) {
	statuses := []core.ChunkStatus{
		core.ChunkStatusPending,
		core.ChunkStatusClaimed,
		core.ChunkStatusExtracting,
		core.ChunkStatusExtracted,
		core.ChunkStatusLoading,
		core.ChunkStatusLoaded,
		core.ChunkStatusFailed,
		core.ChunkStatusRetrying,
	}
	for _, status := range statuses {
		chunks, err := q.ListChunksByStatus(jobID, status)
		if err != nil {
			return false, err
		}
		for _, chunk := range chunks {
			if chunkMatchesTable(chunk, schema, table) {
				return true, nil
			}
		}
	}
	return false, nil
}

// ensureTableChunksEnqueued persists planned chunks when none exist yet for the table.
func ensureTableChunksEnqueued(
	q *queue.ChunkQueue,
	jobID uuid.UUID,
	schema, table string,
	chunks []core.ChunkPlan,
) error {
	exists, err := hasQueuedTableChunks(q, jobID, schema, table)
	if err != nil {
		return err
	}
	if exists {
		return nil
	}
	for i := range chunks {
		chunks[i].JobID = jobID
		chunks[i].Status = core.ChunkStatusPending
		if err := q.Enqueue(&chunks[i]); err != nil {
			return err
		}
	}
	return nil
}

func countPendingTableChunks(q *queue.ChunkQueue, jobID uuid.UUID, schema, table string) (int, error) {
	chunks, err := q.ListChunksByStatus(jobID, core.ChunkStatusPending)
	if err != nil {
		return 0, err
	}
	n := 0
	for _, chunk := range chunks {
		if chunkMatchesTable(chunk, schema, table) {
			n++
		}
	}
	return n, nil
}
