// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"context"
	"time"

	"github.com/ravisharma/sql-optima/engine-go/internal/metadata"
)

const (
	engineVersion        = "0.2.0"
	defaultPollInterval  = 2 * time.Second
	defaultHeartbeatSecs = 15
)

// MigrationEngineWorkerLoop polls the metadata DB for queued Go migration jobs.
type MigrationEngineWorkerLoop struct {
	workerID       string
	meta           MigrationMetadataPort
	claimer        *MigrationJobClaimer
	handler        *MigrationGoJobHandler
	pollEvery      time.Duration
	heartbeatEvery time.Duration
}

func NewMigrationEngineWorkerLoop(
	workerID string,
	meta MigrationMetadataPort,
	masterKey string,
	metadataURL string,
	commandPoller *metadata.CommandPoller,
	runtime MigrationEngineRuntime,
) *MigrationEngineWorkerLoop {
	runtime.WorkerID = workerID
	return &MigrationEngineWorkerLoop{
		workerID:       workerID,
		meta:           meta,
		claimer:        NewMigrationJobClaimer(meta),
		handler:        NewMigrationGoJobHandler(meta, masterKey, metadataURL, commandPoller, runtime),
		pollEvery:      defaultPollInterval,
		heartbeatEvery: defaultHeartbeatSecs * time.Second,
	}
}

// Run blocks until ctx is cancelled.
func (l *MigrationEngineWorkerLoop) Run(ctx context.Context) error {
	heartbeat := time.NewTicker(l.heartbeatEvery)
	defer heartbeat.Stop()

	poll := time.NewTicker(l.pollEvery)
	defer poll.Stop()

	_ = l.meta.UpsertWorkerHeartbeat(ctx, l.workerID, engineVersion, "idle")

	for {
		select {
		case <-ctx.Done():
			_ = l.meta.UpsertWorkerHeartbeat(context.Background(), l.workerID, engineVersion, "stopped")
			return ctx.Err()
		case <-heartbeat.C:
			_ = l.meta.UpsertWorkerHeartbeat(ctx, l.workerID, engineVersion, "idle")
		case <-poll.C:
			job, err := l.claimer.ClaimNext(ctx, l.workerID)
			if err != nil || job == nil {
				continue
			}
			jobCtx, endJobHeartbeats := context.WithCancel(ctx)
			go l.runBusyHeartbeats(jobCtx)
			_ = l.meta.UpsertWorkerHeartbeat(ctx, l.workerID, engineVersion, "busy")
			_ = l.handler.Run(ctx, job)
			endJobHeartbeats()
			_ = l.meta.UpsertWorkerHeartbeat(ctx, l.workerID, engineVersion, "idle")
		}
	}
}

func (l *MigrationEngineWorkerLoop) runBusyHeartbeats(ctx context.Context) {
	ticker := time.NewTicker(l.heartbeatEvery)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			_ = l.meta.UpsertWorkerHeartbeat(context.Background(), l.workerID, engineVersion, "busy")
		}
	}
}
