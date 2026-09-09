// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package transfer

import (
	"context"
	"encoding/json"

	"github.com/google/uuid"
	"github.com/ravisharma/sql-optima/engine-go/internal/core"
	"github.com/ravisharma/sql-optima/engine-go/internal/metadata"
)

// TransferMetadataAdapter implements TransferMetadataPort for *metadata.Client.
type TransferMetadataAdapter struct {
	Client *metadata.Client
}

func NewTransferMetadataAdapter(client *metadata.Client) *TransferMetadataAdapter {
	return &TransferMetadataAdapter{Client: client}
}

var _ TransferMetadataPort = (*TransferMetadataAdapter)(nil)

func (a *TransferMetadataAdapter) UpsertWorkerHeartbeat(ctx context.Context, workerID, engineVersion, status string) error {
	return a.Client.UpsertWorkerHeartbeat(ctx, workerID, engineVersion, status)
}

func (a *TransferMetadataAdapter) ListQueuedTransferJobs(ctx context.Context, limit int) ([]QueuedTransferJob, error) {
	rows, err := a.Client.ListQueuedTransferJobs(ctx, limit)
	if err != nil {
		return nil, err
	}
	out := make([]QueuedTransferJob, len(rows))
	for i, r := range rows {
		out[i] = QueuedTransferJob{JobID: r.JobID, Config: r.Config}
	}
	return out, nil
}

func (a *TransferMetadataAdapter) ClaimQueuedTransferJob(ctx context.Context, jobID uuid.UUID) (bool, error) {
	return a.Client.ClaimQueuedTransferJob(ctx, jobID)
}

func (a *TransferMetadataAdapter) LoadTransferDispatchConfig(ctx context.Context, jobID uuid.UUID) (json.RawMessage, error) {
	return a.Client.LoadTransferDispatchConfig(ctx, jobID)
}

func (a *TransferMetadataAdapter) AppendTransferJobLog(ctx context.Context, jobID uuid.UUID, level, message string) error {
	return a.Client.AppendTransferJobLog(ctx, jobID, level, message)
}

func (a *TransferMetadataAdapter) AppendTransferTableLog(ctx context.Context, jobID uuid.UUID, tableName, level, message string) error {
	return a.Client.AppendTransferTableLog(ctx, jobID, tableName, level, message)
}

func (a *TransferMetadataAdapter) SetTransferJobStatus(ctx context.Context, jobID uuid.UUID, status string) error {
	return a.Client.SetTransferJobStatus(ctx, jobID, status)
}

func (a *TransferMetadataAdapter) SetTransferJobError(ctx context.Context, jobID uuid.UUID, message string) error {
	return a.Client.SetTransferJobError(ctx, jobID, message)
}

func (a *TransferMetadataAdapter) SetTransferTableError(ctx context.Context, jobID uuid.UUID, sourceSchema, sourceTable, message string) error {
	return a.Client.SetTransferTableError(ctx, jobID, sourceSchema, sourceTable, message)
}

func (a *TransferMetadataAdapter) UpdateTransferTableProgress(ctx context.Context, jobID uuid.UUID, tableName, status string, rows int64) error {
	return a.Client.UpdateTransferTableProgress(ctx, jobID, tableName, status, rows)
}

func (a *TransferMetadataAdapter) UpdateTransferJobTotals(ctx context.Context, jobID uuid.UUID, rowsCopied int64, tablesDone int) error {
	return a.Client.UpdateTransferJobTotals(ctx, jobID, rowsCopied, tablesDone)
}

func (a *TransferMetadataAdapter) AckTransferCommand(ctx context.Context, jobID uuid.UUID) error {
	return a.Client.AckTransferCommand(ctx, jobID)
}

func (a *TransferMetadataAdapter) GetTransferCommand(ctx context.Context, jobID uuid.UUID) (core.Command, bool, error) {
	return a.Client.GetTransferCommand(ctx, jobID)
}

func (a *TransferMetadataAdapter) LoadProjectConnection(ctx context.Context, connectionID uuid.UUID) (*metadata.ProjectConnection, error) {
	return a.Client.LoadProjectConnection(ctx, connectionID)
}

func (a *TransferMetadataAdapter) LoadTransferRuntimeSettings(ctx context.Context, jobID uuid.UUID) (int64, *int64, error) {
	return a.Client.LoadTransferRuntimeSettings(ctx, jobID)
}
