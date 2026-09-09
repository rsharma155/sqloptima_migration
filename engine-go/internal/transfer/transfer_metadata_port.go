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

// QueuedTransferJob is a claimed transfer_jobs row.
type QueuedTransferJob struct {
	JobID  uuid.UUID
	Config json.RawMessage
}

// TransferMetadataPort is the metadata DB surface for Transfer workers.
type TransferMetadataPort interface {
	UpsertWorkerHeartbeat(ctx context.Context, workerID, engineVersion, status string) error
	ListQueuedTransferJobs(ctx context.Context, limit int) ([]QueuedTransferJob, error)
	ClaimQueuedTransferJob(ctx context.Context, jobID uuid.UUID) (bool, error)
	LoadTransferDispatchConfig(ctx context.Context, jobID uuid.UUID) (json.RawMessage, error)
	AppendTransferJobLog(ctx context.Context, jobID uuid.UUID, level, message string) error
	AppendTransferTableLog(ctx context.Context, jobID uuid.UUID, tableName, level, message string) error
	SetTransferJobStatus(ctx context.Context, jobID uuid.UUID, status string) error
	SetTransferJobError(ctx context.Context, jobID uuid.UUID, message string) error
	SetTransferTableError(ctx context.Context, jobID uuid.UUID, sourceSchema, sourceTable, message string) error
	UpdateTransferTableProgress(ctx context.Context, jobID uuid.UUID, tableName, status string, rows int64) error
	UpdateTransferJobTotals(ctx context.Context, jobID uuid.UUID, rowsCopied int64, tablesDone int) error
	AckTransferCommand(ctx context.Context, jobID uuid.UUID) error
	GetTransferCommand(ctx context.Context, jobID uuid.UUID) (core.Command, bool, error)
	LoadProjectConnection(ctx context.Context, connectionID uuid.UUID) (*metadata.ProjectConnection, error)
	LoadTransferRuntimeSettings(ctx context.Context, jobID uuid.UUID) (chunkSize int64, maxRowsPerSec *int64, err error)
}

// TransferTableMover copies one table. Tests inject a fake; production uses live adapters.
type TransferTableMover interface {
	Move(
		ctx context.Context,
		jobID uuid.UUID,
		src *metadata.ProjectConnection,
		tgt *metadata.ProjectConnection,
		table TransferTablePayload,
	) (int64, error)
}
