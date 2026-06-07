// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package core_test

import (
	"testing"

	"github.com/google/uuid"
	"github.com/ravisharma/sql-optima/engine-go/internal/core"
)

func TestNewChunkPlanDefaults(t *testing.T) {
	jobID := uuid.New()
	start := "1"
	end := "1000"
	c := core.NewChunkPlan(jobID, "dbo", "orders", 0, "id", &start, &end)

	if c.ID == (uuid.UUID{}) {
		t.Error("chunk ID must not be zero")
	}
	if c.JobID != jobID {
		t.Error("job ID mismatch")
	}
	if c.Status != core.ChunkStatusPending {
		t.Errorf("new chunk status = %q, want PENDING", c.Status)
	}
	if c.RowsMigrated != 0 {
		t.Error("rows_migrated must start at 0")
	}
	if c.CreatedAt.IsZero() {
		t.Error("created_at must not be zero")
	}
}

func TestChunkPlanQualifiedTable(t *testing.T) {
	c := core.NewChunkPlan(uuid.New(), "sales", "orders", 0, "id", nil, nil)
	if got := c.QualifiedTable(); got != "sales.orders" {
		t.Errorf("QualifiedTable() = %q, want %q", got, "sales.orders")
	}
}

func TestTableMetaHasLOB(t *testing.T) {
	withLOB := core.TableMeta{Columns: []core.ColumnMeta{
		{ColumnName: "id", IsLOB: false},
		{ColumnName: "body", IsLOB: true},
	}}
	withoutLOB := core.TableMeta{Columns: []core.ColumnMeta{
		{ColumnName: "id", IsLOB: false},
	}}
	if !withLOB.HasLOB() {
		t.Error("HasLOB must return true when a LOB column is present")
	}
	if withoutLOB.HasLOB() {
		t.Error("HasLOB must return false when no LOB column is present")
	}
}

func TestDefaultJobConfig(t *testing.T) {
	cfg := core.DefaultJobConfig()
	if cfg.ParallelWorkers != 4 {
		t.Errorf("ParallelWorkers = %d, want 4", cfg.ParallelWorkers)
	}
	if cfg.ChunkSize != 10_000 {
		t.Errorf("ChunkSize = %d, want 10000", cfg.ChunkSize)
	}
	if cfg.MinChunkSize >= cfg.MaxChunkSize {
		t.Error("min chunk size must be less than max chunk size")
	}
}
