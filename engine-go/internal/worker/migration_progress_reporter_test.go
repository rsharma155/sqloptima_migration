// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"context"
	"testing"

	"github.com/google/uuid"
)

type progressMetaSpy struct {
	fakeCommandMeta
	tableRows []int64
	jobRows   []int64
}

func (p *progressMetaSpy) UpdateTablePlanProgress(_ context.Context, _ uuid.UUID, _ string, _ string, rows int64) error {
	p.tableRows = append(p.tableRows, rows)
	return nil
}

func (p *progressMetaSpy) UpdateMigrationJobTotals(_ context.Context, _ uuid.UUID, rows int64, _ int) error {
	p.jobRows = append(p.jobRows, rows)
	return nil
}

func TestThrottledChunkProgressReportsFirstBatch(t *testing.T) {
	spy := &progressMetaSpy{}
	jobID := uuid.New()
	reporter := newThrottledChunkProgress(spy, jobID, "orders", JobProgressBase{RowsMigrated: 1000, TablesDone: 1}, 0)
	reporter.report(500)
	if len(spy.tableRows) != 1 || spy.tableRows[0] != 500 {
		t.Fatalf("table progress = %v want [500]", spy.tableRows)
	}
	if len(spy.jobRows) != 1 || spy.jobRows[0] != 1500 {
		t.Fatalf("job progress = %v want [1500]", spy.jobRows)
	}
}

func TestThrottledChunkProgressSkipsSmallIncrements(t *testing.T) {
	spy := &progressMetaSpy{}
	jobID := uuid.New()
	reporter := newThrottledChunkProgress(spy, jobID, "orders", JobProgressBase{}, 0)
	reporter.report(100)
	reporter.report(200)
	if len(spy.tableRows) != 1 {
		t.Fatalf("expected one throttled report, got %d", len(spy.tableRows))
	}
}
