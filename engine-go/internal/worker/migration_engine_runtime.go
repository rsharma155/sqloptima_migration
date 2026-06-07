// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"github.com/ravisharma/sql-optima/engine-go/internal/config"
	"github.com/ravisharma/sql-optima/engine-go/internal/planner"
	"github.com/ravisharma/sql-optima/engine-go/internal/queue"
)

// MigrationEngineRuntime holds data-plane dependencies wired from main.
type MigrationEngineRuntime struct {
	Queue    *queue.ChunkQueue
	ChunkCfg config.ChunkConfig
	WorkerID string
	Sizer    *planner.AdaptiveChunkSizer
}
