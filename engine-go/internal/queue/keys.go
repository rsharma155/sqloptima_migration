// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package queue

import (
	"fmt"
	"strings"

	"github.com/google/uuid"
	"github.com/ravisharma/sql-optima/engine-go/internal/core"
)

// Key-encoding helpers — exact analogs of the Rust key-builder functions.

func chunkKey(jobID, chunkID uuid.UUID) []byte {
	return []byte(jobID.String() + "/" + chunkID.String())
}

func statusKey(jobID uuid.UUID, status core.ChunkStatus, chunkID uuid.UUID) []byte {
	return []byte(fmt.Sprintf("%s/%s/%s", jobID, status, chunkID))
}

func commandKey(jobID uuid.UUID) []byte {
	return []byte(jobID.String())
}

func checkpointKey(jobID uuid.UUID, tableQualified string) []byte {
	return []byte(fmt.Sprintf("%s/%s", jobID, tableQualified))
}

// statusPrefix returns the prefix used to range-scan all chunks of a given
// status for a job: "<job_id>/<STATUS>/".
func statusPrefix(jobID uuid.UUID, status core.ChunkStatus) []byte {
	return []byte(fmt.Sprintf("%s/%s/", jobID, status))
}

// parseChunkIDFromStatusKey extracts the chunk UUID from a status_idx key.
// Key format: "<job_id>/<STATUS>/<chunk_id>"
func parseChunkIDFromStatusKey(key []byte) (uuid.UUID, error) {
	parts := strings.Split(string(key), "/")
	if len(parts) != 3 {
		return uuid.UUID{}, fmt.Errorf("malformed status key %q", key)
	}
	return uuid.Parse(parts[2])
}
