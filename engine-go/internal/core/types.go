// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package core

import (
	"fmt"
	"time"

	"github.com/google/uuid"
)

// JobID and ChunkID are UUID-typed identifiers used throughout the engine.
type (
	JobID   = uuid.UUID
	ChunkID = uuid.UUID
)

// JobStatus represents the lifecycle state of a migration job.
type JobStatus string

const (
	JobStatusPending   JobStatus = "PENDING"
	JobStatusQueued    JobStatus = "QUEUED"
	JobStatusRunning   JobStatus = "RUNNING"
	JobStatusPaused    JobStatus = "PAUSED"
	JobStatusStopped   JobStatus = "STOPPED"
	JobStatusCompleted JobStatus = "COMPLETED"
	JobStatusFailed    JobStatus = "FAILED"
)

// ChunkStatus represents the lifecycle state of a single data chunk.
type ChunkStatus string

const (
	ChunkStatusPending    ChunkStatus = "PENDING"
	ChunkStatusClaimed    ChunkStatus = "CLAIMED"
	ChunkStatusExtracting ChunkStatus = "EXTRACTING"
	ChunkStatusExtracted  ChunkStatus = "EXTRACTED"
	ChunkStatusLoading    ChunkStatus = "LOADING"
	ChunkStatusLoaded     ChunkStatus = "LOADED"
	ChunkStatusFailed     ChunkStatus = "FAILED"
	ChunkStatusRetrying   ChunkStatus = "RETRYING"
)

// JobConfig holds runtime tuning parameters for a migration job.
type JobConfig struct {
	ParallelWorkers       int   `json:"parallel_workers"`
	ChunkSize             int64 `json:"chunk_size"`
	TargetChunkDurationMs int64 `json:"target_chunk_duration_ms"`
	MinChunkSize          int64 `json:"min_chunk_size"`
	MaxChunkSize          int64 `json:"max_chunk_size"`
}

// DefaultJobConfig returns production-ready defaults.
func DefaultJobConfig() JobConfig {
	return JobConfig{
		ParallelWorkers:       4,
		ChunkSize:             10_000,
		TargetChunkDurationMs: 2_000,
		MinChunkSize:          1_000,
		MaxChunkSize:          100_000,
	}
}

// ChunkPlan describes a single data chunk to be extracted and loaded.
// StartKey and EndKey are inclusive and are serialised as strings for
// generality (supports integer PK ranges as well as date ranges).
type ChunkPlan struct {
	ID          ChunkID     `json:"id"`
	JobID       JobID       `json:"job_id"`
	TableSchema string      `json:"table_schema"`
	TableName   string      `json:"table_name"`
	ChunkIndex  uint32      `json:"chunk_index"`
	StartKey    *string     `json:"start_key,omitempty"`
	EndKey      *string     `json:"end_key,omitempty"`
	PKColumn    string      `json:"pk_column"`
	Status      ChunkStatus `json:"status"`
	RowsMigrated int64      `json:"rows_migrated"`
	RetryCount  uint32      `json:"retry_count"`
	Error       *string     `json:"error,omitempty"`
	ClaimedBy   *string     `json:"claimed_by,omitempty"`
	ClaimedAt   *time.Time  `json:"claimed_at,omitempty"`
	ExtractedAt *time.Time  `json:"extracted_at,omitempty"`
	LoadedAt    *time.Time  `json:"loaded_at,omitempty"`
	CreatedAt   time.Time   `json:"created_at"`
}

// NewChunkPlan creates a new PENDING chunk with a fresh UUID.
func NewChunkPlan(jobID JobID, schema, table string, index uint32,
	pkCol string, start, end *string) ChunkPlan {
	return ChunkPlan{
		ID:          uuid.New(),
		JobID:       jobID,
		TableSchema: schema,
		TableName:   table,
		ChunkIndex:  index,
		PKColumn:    pkCol,
		StartKey:    start,
		EndKey:      end,
		Status:      ChunkStatusPending,
		CreatedAt:   time.Now().UTC(),
	}
}

// QualifiedTable returns "schema.table".
func (c ChunkPlan) QualifiedTable() string {
	return fmt.Sprintf("%s.%s", c.TableSchema, c.TableName)
}

// ColumnMeta describes a single column in a source table.
type ColumnMeta struct {
	ColumnName string `json:"column_name"`
	DataType   string `json:"data_type"`
	IsNullable bool   `json:"is_nullable"`
	IsIdentity bool   `json:"is_identity"`
	IsLOB      bool   `json:"is_lob"`
	MaxLength  int32  `json:"max_length"`
	Precision  uint8  `json:"precision"`
	Scale      uint8  `json:"scale"`
}

// TableMeta holds discovery metadata for a source table.
type TableMeta struct {
	SchemaName       string       `json:"schema_name"`
	TableName        string       `json:"table_name"`
	RowCountEstimate int64        `json:"row_count_estimate"`
	PKColumn         *string      `json:"pk_column,omitempty"`
	Columns          []ColumnMeta `json:"columns"`
}

// QualifiedName returns "schema.table".
func (t TableMeta) QualifiedName() string {
	return fmt.Sprintf("%s.%s", t.SchemaName, t.TableName)
}

// HasLOB reports whether any column in this table requires LOB streaming.
func (t TableMeta) HasLOB() bool {
	for _, c := range t.Columns {
		if c.IsLOB {
			return true
		}
	}
	return false
}
