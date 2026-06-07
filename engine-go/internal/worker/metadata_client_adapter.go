// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"context"
	"encoding/json"

	"github.com/google/uuid"
	"github.com/ravisharma/sql-optima/engine-go/internal/core"
	"github.com/ravisharma/sql-optima/engine-go/internal/metadata"
)

// MetadataClientAdapter implements MigrationMetadataPort for *metadata.Client.
type MetadataClientAdapter struct {
	Client *metadata.Client
}

func (a *MetadataClientAdapter) UpsertWorkerHeartbeat(ctx context.Context, workerID, engineVersion, status string) error {
	return a.Client.UpsertWorkerHeartbeat(ctx, workerID, engineVersion, status)
}

func (a *MetadataClientAdapter) ListQueuedGoJobs(ctx context.Context, limit int) ([]QueuedJob, error) {
	rows, err := a.Client.ListQueuedGoJobs(ctx, limit)
	if err != nil {
		return nil, err
	}
	out := make([]QueuedJob, len(rows))
	for i, r := range rows {
		out[i] = QueuedJob{JobID: r.JobID, Config: r.Config}
	}
	return out, nil
}

func (a *MetadataClientAdapter) ClaimQueuedJob(ctx context.Context, jobID uuid.UUID) (bool, error) {
	return a.Client.ClaimQueuedJob(ctx, jobID)
}

func (a *MetadataClientAdapter) LoadJobDispatchConfig(ctx context.Context, jobID uuid.UUID) (json.RawMessage, error) {
	return a.Client.LoadJobDispatchConfig(ctx, jobID)
}

func (a *MetadataClientAdapter) AppendMigrationJobLog(ctx context.Context, jobID uuid.UUID, level, message string) error {
	return a.Client.AppendMigrationJobLog(ctx, jobID, level, message)
}

func (a *MetadataClientAdapter) SetMigrationJobStatus(ctx context.Context, jobID uuid.UUID, status string) error {
	return a.Client.SetMigrationJobStatus(ctx, jobID, status)
}

func (a *MetadataClientAdapter) SetMigrationJobError(ctx context.Context, jobID uuid.UUID, message string) error {
	return a.Client.SetMigrationJobError(ctx, jobID, message)
}

func (a *MetadataClientAdapter) UpdateTablePlanProgress(ctx context.Context, jobID uuid.UUID, tableName, status string, rows int64) error {
	return a.Client.UpdateTablePlanProgress(ctx, jobID, tableName, status, rows)
}

func (a *MetadataClientAdapter) AckCommand(ctx context.Context, jobID uuid.UUID) error {
	return a.Client.AckCommand(ctx, jobID)
}

func (a *MetadataClientAdapter) GetCommand(
	ctx context.Context, jobID uuid.UUID,
) (core.Command, bool, error) {
	return a.Client.GetCommand(ctx, jobID)
}

func (a *MetadataClientAdapter) LoadProjectConnection(
	ctx context.Context, connectionID uuid.UUID,
) (*metadata.ProjectConnection, error) {
	return a.Client.LoadProjectConnection(ctx, connectionID)
}

func (a *MetadataClientAdapter) UpdateMigrationJobTotals(
	ctx context.Context, jobID uuid.UUID, rowsMigrated int64, tablesDone int,
) error {
	return a.Client.UpdateMigrationJobTotals(ctx, jobID, rowsMigrated, tablesDone)
}

func (a *MetadataClientAdapter) InsertMigrationQuarantine(
	ctx context.Context,
	jobID uuid.UUID,
	tableSchema, tableName string,
	chunkIndex uint32,
	pkColumn string,
	startKey, endKey *string,
	errMsg string,
) error {
	return a.Client.InsertMigrationQuarantine(
		ctx, jobID, tableSchema, tableName, chunkIndex, pkColumn, startKey, endKey, errMsg,
	)
}
