// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/google/uuid"
	"github.com/ravisharma/sql-optima/engine-go/internal/core"
	"github.com/ravisharma/sql-optima/engine-go/internal/metadata"
)

// MigrationMetadataPort abstracts metadata DB operations used by the worker loop.
type MigrationMetadataPort interface {
	UpsertWorkerHeartbeat(ctx context.Context, workerID, engineVersion, status string) error
	ListQueuedGoJobs(ctx context.Context, limit int) ([]QueuedJob, error)
	ClaimQueuedJob(ctx context.Context, jobID uuid.UUID) (bool, error)
	LoadJobDispatchConfig(ctx context.Context, jobID uuid.UUID) (json.RawMessage, error)
	AppendMigrationJobLog(ctx context.Context, jobID uuid.UUID, level, message string) error
	SetMigrationJobStatus(ctx context.Context, jobID uuid.UUID, status string) error
	SetMigrationJobError(ctx context.Context, jobID uuid.UUID, message string) error
	UpdateTablePlanProgress(ctx context.Context, jobID uuid.UUID, tableName, status string, rows int64) error
	AckCommand(ctx context.Context, jobID uuid.UUID) error
	GetCommand(ctx context.Context, jobID uuid.UUID) (core.Command, bool, error)
	LoadProjectConnection(ctx context.Context, connectionID uuid.UUID) (*metadata.ProjectConnection, error)
	UpdateMigrationJobTotals(ctx context.Context, jobID uuid.UUID, rowsMigrated int64, tablesDone int) error
	InsertMigrationQuarantine(
		ctx context.Context,
		jobID uuid.UUID,
		tableSchema, tableName string,
		chunkIndex uint32,
		pkColumn string,
		startKey, endKey *string,
		errMsg string,
	) error
}

// QueuedJob is a minimal queued-job view for the worker loop.
type QueuedJob struct {
	JobID  uuid.UUID
	Config json.RawMessage
}

// MigrationJobClaimer claims queued jobs for this worker instance.
type MigrationJobClaimer struct {
	meta MigrationMetadataPort
}

func NewMigrationJobClaimer(meta MigrationMetadataPort) *MigrationJobClaimer {
	return &MigrationJobClaimer{meta: meta}
}

// ClaimNext returns the first queued job this worker successfully claimed.
func (c *MigrationJobClaimer) ClaimNext(ctx context.Context, _ string) (*QueuedJob, error) {
	jobs, err := c.meta.ListQueuedGoJobs(ctx, 5)
	if err != nil {
		return nil, err
	}
	for _, job := range jobs {
		claimed, err := c.meta.ClaimQueuedJob(ctx, job.JobID)
		if err != nil {
			return nil, err
		}
		if !claimed {
			continue
		}
		cfg, err := c.meta.LoadJobDispatchConfig(ctx, job.JobID)
		if err != nil {
			return nil, fmt.Errorf("load config for job %s: %w", job.JobID, err)
		}
		return &QueuedJob{JobID: job.JobID, Config: cfg}, nil
	}
	return nil, nil
}
