// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package queue

// bbolt bucket names — map 1-to-1 with the RocksDB column families they replace.
//
// Layout mirrors the Rust queue crate:
//
//	chunks      │ key: "<job_id>/<chunk_id>"              │ value: JSON ChunkPlan
//	status_idx  │ key: "<job_id>/<STATUS>/<chunk_id>"     │ value: empty (index only)
//	commands    │ key: "<job_id>"                          │ value: Command string
//	checkpoints │ key: "<job_id>/<schema.table>"           │ value: "<chunk_id>"
var (
	bucketChunks      = []byte("chunks")
	bucketStatusIdx   = []byte("status_idx")
	bucketCommands    = []byte("commands")
	bucketCheckpoints = []byte("checkpoints")
)

var allBuckets = [][]byte{
	bucketChunks,
	bucketStatusIdx,
	bucketCommands,
	bucketCheckpoints,
}
