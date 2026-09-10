// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package transfer

import (
	"context"
	"time"
)

const transferEngineVersion = "0.2.1"

// TransferEngineWorkerLoop polls transfer_jobs for queued work.
type TransferEngineWorkerLoop struct {
	workerID  string
	meta      TransferMetadataPort
	claimer   *TransferJobClaimer
	handler   *TransferGoJobHandler
	pollEvery time.Duration
}

func NewTransferEngineWorkerLoop(
	workerID string,
	meta TransferMetadataPort,
	handler *TransferGoJobHandler,
) *TransferEngineWorkerLoop {
	return &TransferEngineWorkerLoop{
		workerID:  workerID,
		meta:      meta,
		claimer:   NewTransferJobClaimer(meta),
		handler:   handler,
		pollEvery: 2 * time.Second,
	}
}

func (l *TransferEngineWorkerLoop) Run(ctx context.Context) error {
	poll := time.NewTicker(l.pollEvery)
	defer poll.Stop()
	heartbeat := time.NewTicker(15 * time.Second)
	defer heartbeat.Stop()
	_ = l.meta.UpsertWorkerHeartbeat(ctx, l.workerID, transferEngineVersion, "idle")

	for {
		select {
		case <-ctx.Done():
			_ = l.meta.UpsertWorkerHeartbeat(context.Background(), l.workerID, transferEngineVersion, "stopped")
			return ctx.Err()
		case <-heartbeat.C:
			_ = l.meta.UpsertWorkerHeartbeat(ctx, l.workerID, transferEngineVersion, "idle")
		case <-poll.C:
			job, err := l.claimer.ClaimNext(ctx)
			if err != nil || job == nil {
				continue
			}
			_ = l.meta.UpsertWorkerHeartbeat(ctx, l.workerID, transferEngineVersion, "busy")
			_ = l.handler.Run(ctx, job)
			_ = l.meta.UpsertWorkerHeartbeat(ctx, l.workerID, transferEngineVersion, "idle")
		}
	}
}
