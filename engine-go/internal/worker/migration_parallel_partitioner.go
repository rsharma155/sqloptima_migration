// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"github.com/ravisharma/sql-optima/engine-go/internal/core"
)

const (
	strategyParallelChunked = "parallel_chunked"
	maxParallelWorkers      = 32
)

// isParallelChunkedStrategy reports whether the dispatch strategy requests parallel workers.
func isParallelChunkedStrategy(strategy string) bool {
	return strategy == strategyParallelChunked
}

// effectiveParallelWorkers returns a clamped worker count from the dispatch payload.
func effectiveParallelWorkers(workers int) int {
	if workers < 1 {
		return 1
	}
	if workers > maxParallelWorkers {
		return maxParallelWorkers
	}
	return workers
}

// PartitionChunks splits a chunk plan into up to numWorkers contiguous groups.
// Mirrors Python PartitionStrategy.compute_deterministic_ranges grouping.
func PartitionChunks(chunks []core.ChunkPlan, numWorkers int) [][]core.ChunkPlan {
	if len(chunks) == 0 {
		return nil
	}
	if numWorkers <= 1 {
		return [][]core.ChunkPlan{chunks}
	}

	chunksPerPartition := len(chunks) / numWorkers
	if chunksPerPartition < 1 {
		chunksPerPartition = 1
	}

	partitions := make([][]core.ChunkPlan, 0, numWorkers)
	for i := 0; i < len(chunks); i += chunksPerPartition {
		end := i + chunksPerPartition
		if end > len(chunks) {
			end = len(chunks)
		}
		partitions = append(partitions, chunks[i:end])
	}
	return partitions
}
