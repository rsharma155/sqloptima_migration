// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package transfer

import (
	"context"
	"fmt"
)

// TransferJobClaimer claims queued transfer_jobs for this worker.
type TransferJobClaimer struct {
	meta TransferMetadataPort
}

func NewTransferJobClaimer(meta TransferMetadataPort) *TransferJobClaimer {
	return &TransferJobClaimer{meta: meta}
}

func (c *TransferJobClaimer) ClaimNext(ctx context.Context) (*QueuedTransferJob, error) {
	jobs, err := c.meta.ListQueuedTransferJobs(ctx, 5)
	if err != nil {
		return nil, err
	}
	for _, job := range jobs {
		claimed, err := c.meta.ClaimQueuedTransferJob(ctx, job.JobID)
		if err != nil {
			return nil, err
		}
		if !claimed {
			continue
		}
		cfg, err := c.meta.LoadTransferDispatchConfig(ctx, job.JobID)
		if err != nil {
			return nil, fmt.Errorf("load transfer config for job %s: %w", job.JobID, err)
		}
		return &QueuedTransferJob{JobID: job.JobID, Config: cfg}, nil
	}
	return nil, nil
}
