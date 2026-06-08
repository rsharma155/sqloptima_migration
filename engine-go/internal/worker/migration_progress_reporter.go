// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"context"
	"sync"
	"time"

	"github.com/google/uuid"

	"github.com/ravisharma/sql-optima/engine-go/internal/loader"
)

const (
	progressRowBatch   int64 = 1000
	progressMinSpacing       = 2 * time.Second
)

// JobProgressBase carries completed job counters before the current table starts.
type JobProgressBase struct {
	RowsMigrated int64
	TablesDone   int
}

type throttledChunkProgress struct {
	meta      MigrationMetadataPort
	jobID     uuid.UUID
	tableName string
	base      JobProgressBase
	chunkBase int64

	mu         sync.Mutex
	lastReport int64
	lastAt     time.Time
}

func newThrottledChunkProgress(
	meta MigrationMetadataPort,
	jobID uuid.UUID,
	tableName string,
	base JobProgressBase,
	chunkBase int64,
) *throttledChunkProgress {
	return &throttledChunkProgress{
		meta:      meta,
		jobID:     jobID,
		tableName: tableName,
		base:      base,
		chunkBase: chunkBase,
		lastAt:    time.Time{},
	}
}

func (p *throttledChunkProgress) callback() loader.RowProgressFunc {
	return func(chunkRows int64) {
		p.report(chunkRows)
	}
}

func (p *throttledChunkProgress) report(chunkRows int64) {
	tableRows := p.chunkBase + chunkRows

	p.mu.Lock()
	defer p.mu.Unlock()
	if chunkRows > 0 &&
		tableRows-p.lastReport < progressRowBatch &&
		!p.lastAt.IsZero() &&
		time.Since(p.lastAt) < progressMinSpacing {
		return
	}
	p.lastReport = tableRows
	p.lastAt = time.Now()

	ctx := context.Background()
	_ = p.meta.UpdateTablePlanProgress(ctx, p.jobID, p.tableName, "migrating", tableRows)
	_ = p.meta.UpdateMigrationJobTotals(
		ctx, p.jobID, p.base.RowsMigrated+tableRows, p.base.TablesDone,
	)
}
